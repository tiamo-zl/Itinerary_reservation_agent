"""制度结构化存储（PostgreSQL）。

职责：
- policy_clauses：条款树节点；
- policy_edges：引用/例外/父子关系，支撑图扩展；
- policy_tables：结构化表格，不做文本切分；
- 关键词召回：pg_trgm（ILIKE + similarity），替代 SQLite FTS5。

表结构由 Alembic 管理；`init()` 保留为空操作，兼容旧调用。
"""

import json

from itinerary_agent.domain.models import PolicyTable
from itinerary_agent.infra.db import Database


class PostgresPolicyStore:
    def __init__(self, db: Database):
        self.db = db

    async def init(self) -> None:
        """表结构由 Alembic 负责；这里只做连接可用性检查。"""
        await self.db.fetchone("SELECT 1 AS ok")

    async def upsert_clause(self, data: dict) -> None:
        await self.db.execute(
            "INSERT INTO policy_clauses (clause_id, tenant_id, doc_id, parent_id, "
            "path, clause_type, title, text, table_id, policy_version, effective_from, "
            "effective_to, order_no) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (clause_id) DO UPDATE SET "
            "tenant_id=EXCLUDED.tenant_id, doc_id=EXCLUDED.doc_id, "
            "parent_id=EXCLUDED.parent_id, path=EXCLUDED.path, "
            "clause_type=EXCLUDED.clause_type, title=EXCLUDED.title, "
            "text=EXCLUDED.text, table_id=EXCLUDED.table_id, "
            "policy_version=EXCLUDED.policy_version, "
            "effective_from=EXCLUDED.effective_from, "
            "effective_to=EXCLUDED.effective_to, order_no=EXCLUDED.order_no",
            (
                data["clause_id"], data["tenant_id"], data["doc_id"], data.get("parent_id"),
                data["path"], data["clause_type"], data["title"], data["text"],
                data.get("table_id"), data["policy_version"], data.get("effective_from"),
                data.get("effective_to"), data["order_no"],
            ),
        )

    async def add_edge(self, source_id: str, relation: str, target_id: str) -> None:
        await self.db.execute(
            "INSERT INTO policy_edges (source_id, relation, target_id) "
            "VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
            (source_id, relation, target_id),
        )

    async def add_review(self, clause_id: str, ref_text: str, reason: str) -> None:
        # 无法解析的引用进入人工校对队列，不能静默丢弃。
        # 重复入库同一 bundle 时避免产生重复待办。
        await self.db.execute(
            "INSERT INTO policy_ingest_reviews "
            "(clause_id, ref_text, reason, created_at) "
            "SELECT ?, ?, ?, now() WHERE NOT EXISTS ("
            "  SELECT 1 FROM policy_ingest_reviews "
            "  WHERE clause_id = ? AND ref_text = ? AND status = 'pending'"
            ")",
            (clause_id, ref_text, reason, clause_id, ref_text),
        )

    async def upsert_table(self, table: PolicyTable) -> None:
        await self.db.execute(
            "INSERT INTO policy_tables "
            "(table_id, source_clause_id, columns_json, rows_json) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (table_id) DO UPDATE SET "
            "source_clause_id=EXCLUDED.source_clause_id, "
            "columns_json=EXCLUDED.columns_json, rows_json=EXCLUDED.rows_json",
            (
                table.table_id, table.source_clause_id,
                json.dumps(table.columns, ensure_ascii=False),
                json.dumps(table.rows, ensure_ascii=False),
            ),
        )

    async def get_table(self, table_id: str) -> PolicyTable | None:
        row = await self.db.fetchone(
            "SELECT * FROM policy_tables WHERE table_id = ?", (table_id,)
        )
        if row is None:
            return None
        return PolicyTable(
            table_id=row["table_id"],
            source_clause_id=row["source_clause_id"],
            columns=json.loads(row["columns_json"]),
            rows=json.loads(row["rows_json"]),
        )

    async def get_clause(self, clause_id: str) -> dict | None:
        row = await self.db.fetchone(
            "SELECT * FROM policy_clauses WHERE clause_id = ?", (clause_id,)
        )
        return dict(row) if row else None

    async def keyword_search(self, tenant_id: str, policy_version: str,
                             query: str, limit: int = 10) -> list[dict]:
        """中文子串召回：pg_trgm 索引 + ILIKE，按相似度排序。

        注意 SQL 里的 `%%` 是 psycopg 对字面量百分号的转义。
        """
        rows = await self.db.fetchall(
            "SELECT c.* FROM policy_clauses c "
            "WHERE c.tenant_id = ? AND c.policy_version = ? "
            "AND (c.title ILIKE '%%' || ? || '%%' "
            "     OR c.text ILIKE '%%' || ? || '%%') "
            "ORDER BY GREATEST(similarity(c.title, ?), similarity(c.text, ?)) DESC "
            "LIMIT ?",
            (tenant_id, policy_version, query, query, query, query, limit),
        )
        return [dict(row) for row in rows]

    async def list_clauses(self, tenant_id: str,
                           policy_version: str) -> list[dict]:
        rows = await self.db.fetchall(
            "SELECT * FROM policy_clauses WHERE tenant_id = ? "
            "AND policy_version = ? ORDER BY path, order_no",
            (tenant_id, policy_version),
        )
        return [dict(row) for row in rows]

    async def list_edges(self, tenant_id: str,
                         policy_version: str) -> list[dict]:
        rows = await self.db.fetchall(
            "SELECT e.source_id, e.relation, e.target_id FROM policy_edges e "
            "JOIN policy_clauses c ON c.clause_id = e.source_id "
            "WHERE c.tenant_id = ? AND c.policy_version = ?",
            (tenant_id, policy_version),
        )
        return [dict(row) for row in rows]

    async def list_references(self, tenant_id: str,
                              policy_version: str) -> dict[str, list[str]]:
        rows = await self.db.fetchall(
            "SELECT e.source_id, e.target_id FROM policy_edges e "
            "JOIN policy_clauses c ON c.clause_id = e.source_id "
            "WHERE c.tenant_id = ? AND c.policy_version = ? "
            "AND e.relation = 'references'",
            (tenant_id, policy_version),
        )
        result: dict[str, list[str]] = {}
        for row in rows:
            result.setdefault(row["source_id"], []).append(row["target_id"])
        return result

    async def list_pending_reviews(self) -> list[dict]:
        rows = await self.db.fetchall(
            "SELECT review_id, clause_id, ref_text, reason, created_at "
            "FROM policy_ingest_reviews WHERE status = 'pending' "
            "ORDER BY review_id"
        )
        return [dict(row) for row in rows]

    async def reindex_keyword_indexes(self) -> None:
        """重建 pg_trgm 索引；只由知识 CLI 调用。"""
        await self.db.execute(
            "REINDEX INDEX idx_policy_clauses_title_trgm"
        )
        await self.db.execute(
            "REINDEX INDEX idx_policy_clauses_text_trgm"
        )

    async def expand(self, seed_ids: list[str], hops: int = 1) -> list[dict]:
        """沿引用/例外/父子边扩展条款，返回带 refs 的节点集合。

        步骤：
        1. 从种子条款开始做 BFS；
        2. 每跳沿 policy_edges 找目标条款；
        3. 同时带上父条款，保留章节适用范围；
        4. 批量取回全部条款；
        5. 附带每条条款的 references 列表。
        """
        # 步骤 1：初始化已访问集合和当前扩展前沿。
        visited = set(seed_ids)
        frontier = set(seed_ids)

        # 步骤 2/3：逐跳扩展引用、例外边，并向上补父条款。
        for _ in range(hops):
            if not frontier:
                break
            placeholders = ",".join("?" for _ in frontier)
            rows = await self.db.fetchall(
                f"SELECT target_id FROM policy_edges WHERE source_id IN ({placeholders})",
                tuple(frontier),
            )
            next_ids = {row["target_id"] for row in rows} - visited

            # 同时向上带出父条款（章节适用范围），避免只检索到局部条件。
            for clause_id in list(frontier):
                row = await self.db.fetchone(
                    "SELECT parent_id FROM policy_clauses WHERE clause_id = ?", (clause_id,)
                )
                if row and row["parent_id"]:
                    next_ids.add(row["parent_id"])

            visited.update(next_ids)
            frontier = next_ids

        if not visited:
            return []

        # 步骤 4：一次取回所有命中条款。
        placeholders = ",".join("?" for _ in visited)
        rows = await self.db.fetchall(
            f"SELECT * FROM policy_clauses WHERE clause_id IN ({placeholders}) ORDER BY path",
            tuple(visited),
        )

        # 步骤 5：补齐每个条款的引用列表，方便前端展示依据。
        edge_rows = await self.db.fetchall(
            f"SELECT source_id, target_id FROM policy_edges "
            f"WHERE relation = 'references' AND source_id IN ({placeholders})",
            tuple(visited),
        )
        refs_by_source: dict[str, list[str]] = {}
        for edge in edge_rows:
            refs_by_source.setdefault(edge["source_id"], []).append(edge["target_id"])

        result = []
        for row in rows:
            item = dict(row)
            item["refs"] = refs_by_source.get(item["clause_id"], [])
            result.append(item)
        return result
