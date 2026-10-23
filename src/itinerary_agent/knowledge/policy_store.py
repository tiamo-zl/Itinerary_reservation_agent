"""制度结构化存储（SQLite）。

职责：
- policy_clauses：条款树节点；
- policy_edges：引用/例外/父子关系，支撑图扩展；
- policy_tables：结构化表格，不做文本切分；
- policy_fts：中文关键词召回（FTS5 trigram）。

demo 约定 table_id 带租户/版本前缀；生产应改为复合主键。
"""

import json

from itinerary_agent.domain.models import PolicyTable
from itinerary_agent.infra.db import Database

SCHEMA = """
CREATE TABLE IF NOT EXISTS policy_clauses (
  clause_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, doc_id TEXT NOT NULL,
  parent_id TEXT, path TEXT NOT NULL, clause_type TEXT NOT NULL,
  title TEXT NOT NULL, text TEXT NOT NULL, table_id TEXT,
  policy_version TEXT NOT NULL, effective_from TEXT, effective_to TEXT,
  order_no INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS policy_edges (
  source_id TEXT NOT NULL, relation TEXT NOT NULL, target_id TEXT NOT NULL,
  PRIMARY KEY (source_id, relation, target_id)
);
CREATE TABLE IF NOT EXISTS policy_tables (
  table_id TEXT PRIMARY KEY, source_clause_id TEXT NOT NULL,
  columns_json TEXT NOT NULL, rows_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policy_definitions (
  definition_id TEXT PRIMARY KEY, term TEXT NOT NULL, text TEXT NOT NULL,
  source_clause_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policy_ingest_reviews (
  review_id INTEGER PRIMARY KEY AUTOINCREMENT,
  clause_id TEXT NOT NULL, ref_text TEXT NOT NULL, reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS policy_fts
USING fts5(clause_id UNINDEXED, title, text, tokenize='trigram');
"""


class PolicyStore:
    def __init__(self, db: Database):
        self.db = db

    async def init(self) -> None:
        # IF NOT EXISTS 保证重复启动不会破坏已有制度数据。
        await self.db.conn.executescript(SCHEMA)
        await self.db.conn.commit()

    async def upsert_clause(self, data: dict) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO policy_clauses (clause_id, tenant_id, doc_id, parent_id, "
            "path, clause_type, title, text, table_id, policy_version, effective_from, "
            "effective_to, order_no) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data["clause_id"], data["tenant_id"], data["doc_id"], data.get("parent_id"),
                data["path"], data["clause_type"], data["title"], data["text"],
                data.get("table_id"), data["policy_version"], data.get("effective_from"),
                data.get("effective_to"), data["order_no"],
            ),
        )
        # FTS 表不参与 INSERT OR REPLACE，先删后插保持同步。
        await self.db.execute("DELETE FROM policy_fts WHERE clause_id = ?", (data["clause_id"],))
        await self.db.execute(
            "INSERT INTO policy_fts (clause_id, title, text) VALUES (?, ?, ?)",
            (data["clause_id"], data["title"], data["text"]),
        )

    async def add_edge(self, source_id: str, relation: str, target_id: str) -> None:
        await self.db.execute(
            "INSERT OR IGNORE INTO policy_edges (source_id, relation, target_id) "
            "VALUES (?, ?, ?)",
            (source_id, relation, target_id),
        )

    async def add_review(self, clause_id: str, ref_text: str, reason: str) -> None:
        # 无法解析的引用进入人工校对队列，不能静默丢弃。
        await self.db.execute(
            "INSERT INTO policy_ingest_reviews (clause_id, ref_text, reason, created_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (clause_id, ref_text, reason),
        )

    async def upsert_table(self, table: PolicyTable) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO policy_tables "
            "(table_id, source_clause_id, columns_json, rows_json) VALUES (?, ?, ?, ?)",
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
        # 把用户输入包成短语，避免 FTS5 把引号/运算符解释成查询语法。
        safe = query.replace('"', '""')
        fts_query = f'"{safe}"'
        rows = await self.db.fetchall(
            "SELECT c.* FROM policy_fts f JOIN policy_clauses c ON c.clause_id = f.clause_id "
            "WHERE policy_fts MATCH ? AND c.tenant_id = ? AND c.policy_version = ? "
            "ORDER BY rank LIMIT ?",
            (fts_query, tenant_id, policy_version, limit),
        )
        return [dict(row) for row in rows]

    async def expand(self, seed_ids: list[str], hops: int = 1) -> list[dict]:
        """沿引用/例外/父子边扩展条款，返回带 refs 的节点集合。"""
        visited = set(seed_ids)
        frontier = set(seed_ids)

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
        placeholders = ",".join("?" for _ in visited)
        rows = await self.db.fetchall(
            f"SELECT * FROM policy_clauses WHERE clause_id IN ({placeholders}) ORDER BY path",
            tuple(visited),
        )
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
