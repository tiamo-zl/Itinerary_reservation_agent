"""制度检索服务：混合召回 → 图扩展 → context pack。

返回的 PolicyContext 只包含条款/表格摘要和引用 ID；
完整制度文本不会进入 LangGraph 状态。
"""

from itinerary_agent.domain.models import (
    CallContext,
    PolicyClause,
    PolicyContext,
    PolicyTable,
)
from itinerary_agent.knowledge.retrieval import CITY_TIERS, rrf_fuse


def _row_matches(row: dict, filters) -> bool:
    """按职级/城市过滤表格行；无 filters 时全部保留。"""
    if filters is None:
        return True
    level = row.get("职级")
    if filters.employee_level and level and level != filters.employee_level:
        return False
    city = row.get("城市")
    return not (
        filters.city_tier is not None
        and city
        and CITY_TIERS.get(city) != filters.city_tier
    )


class KnowledgeService:
    def __init__(self, embedder, policy_store, dense_store, policy_version: str,
                 seed_top_k: int = 8, graph_hops: int = 2,
                 max_expanded_clauses: int = 20):
        self.embedder = embedder
        self.policy_store = policy_store
        self.dense_store = dense_store
        self.policy_version = policy_version
        self.seed_top_k = seed_top_k
        self.graph_hops = graph_hops
        self.max_expanded_clauses = max_expanded_clauses

    async def search_policy(self, ctx, query: str,
                            filters=None) -> PolicyContext:
        """混合召回并组装制度上下文。

        步骤：
        1. query → embedding 向量；
        2. 向量召回 + FTS5 关键词召回；
        3. RRF 融合并截取种子条款；
        4. 沿引用/例外/父子边做图扩展；
        5. 取出并过滤结构化表格；
        6. 组装 PolicyContext，标记 degraded/insufficient。
        """
        try:
            # 步骤 1：把查询转成向量。
            call_ctx = CallContext(
                trace_id=ctx.trace_id, tenant_id=ctx.tenant_id, purpose="embed"
            )
            vector = (await self.embedder.embed(call_ctx, [query]))[0]

            # 步骤 2：向量召回和关键词召回各自独立容错。
            dense = self.dense_store.search(
                ctx.tenant_id, self.policy_version, vector, 10
            )
            try:
                keyword = await self.policy_store.keyword_search(
                    ctx.tenant_id, self.policy_version, query, 10
                )
            except Exception:  # noqa: BLE001 - 关键词失败不应影响向量召回
                keyword = []

            # 步骤 3：用 RRF 融合两路排名，取前 seed_top_k 个条款。
            seed_ids = rrf_fuse(
                [hit["clause_id"] for hit in keyword],
                [hit["clause_id"] for hit in dense],
            )[:self.seed_top_k]
            if not seed_ids:
                return PolicyContext(
                    clauses=[], tables=[], citations=[],
                    policy_version=self.policy_version,
                    insufficient=True,
                    trace={"reason": "no_seed"},
                )

            # 步骤 4：图扩展，带出引用、例外和父章节。
            clauses = await self.policy_store.expand(
                seed_ids, hops=self.graph_hops
            )
            clauses = clauses[:self.max_expanded_clauses]

            # 步骤 5：按 table_id 取结构化表格，并按职级/城市过滤行。
            tables: list[PolicyTable] = []
            missing_table = False
            for clause in clauses:
                if not clause.get("table_id"):
                    continue
                table = await self.policy_store.get_table(clause["table_id"])
                if table is None:
                    missing_table = True
                    continue
                if filters is not None:
                    rows = [row for row in table.rows if _row_matches(row, filters)]
                    if not rows:
                        # 有表格但没有任何行适用于当前职级/城市，同样视为信息不足。
                        missing_table = True
                        continue
                    table = table.model_copy(update={"rows": rows})
                if table.table_id not in {item.table_id for item in tables}:
                    tables.append(table)

            # 步骤 6：组装 context pack；表格缺失意味着信息不足。
            return PolicyContext(
                clauses=[
                    PolicyClause(
                        clause_id=clause["clause_id"], path=clause["path"],
                        title=clause["title"], text=clause["text"],
                        clause_type=clause["clause_type"],
                        policy_version=clause["policy_version"],
                        table_id=clause.get("table_id"),
                        refs=clause.get("refs", []),
                    )
                    for clause in clauses
                ],
                tables=tables,
                citations=[clause["clause_id"] for clause in clauses],
                policy_version=self.policy_version,
                insufficient=not clauses or missing_table,
                trace={
                    "seed_count": len(seed_ids),
                    "expanded_count": len(clauses),
                    "missing_table": missing_table,
                },
            )
        except Exception:  # noqa: BLE001 - 依赖不可用时降级而不是拖垮主流程
            # 依赖不可用：主流程继续，规则引擎仍然可以判定差标。
            return PolicyContext(
                clauses=[], tables=[], citations=[],
                policy_version=self.policy_version,
                degraded=True, insufficient=True,
            )
