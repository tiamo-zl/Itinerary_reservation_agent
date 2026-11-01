"""检索评测用的内存条款存储。

和 PostgresPolicyStore 保持相同的 expand 语义（引用/例外边 + 父条款），
让评测不依赖数据库或 Milvus，可在 CI 中稳定运行。
"""

from itinerary_agent.domain.models import PolicyTable


class MemoryPolicyStore:
    def __init__(self, kb: dict):
        self.clauses = {item["clause_id"]: item for item in kb["clauses"]}
        self.edges = kb.get("edges", [])
        self.tables = {
            table["table_id"]: PolicyTable.model_validate(table)
            for table in kb.get("tables", [])
        }

    async def keyword_search(self, tenant_id: str, policy_version: str,
                             query: str, limit: int = 10) -> list[dict]:
        hits = [
            clause for clause in self.clauses.values()
            if query in clause.get("title", "")
            or query in clause.get("text", "")
        ]
        hits.sort(key=lambda item: item.get("path", ""))
        return hits[:limit]

    async def expand(self, seed_ids: list[str], hops: int = 1) -> list[dict]:
        visited = set(seed_ids)
        frontier = set(seed_ids)
        for _ in range(hops):
            next_ids: set[str] = set()
            for edge in self.edges:
                if edge["source_id"] in frontier:
                    next_ids.add(edge["target_id"])
            for clause_id in list(frontier):
                parent = self.clauses.get(clause_id, {}).get("parent_id")
                if parent:
                    next_ids.add(parent)
            next_ids -= visited
            visited.update(next_ids)
            frontier = next_ids
            if not frontier:
                break

        refs_by_source: dict[str, list[str]] = {}
        for edge in self.edges:
            if edge["relation"] == "references":
                refs_by_source.setdefault(edge["source_id"], []).append(
                    edge["target_id"]
                )
        result = []
        for clause_id in sorted(
            visited, key=lambda cid: self.clauses[cid].get("path", "")
        ):
            clause = dict(self.clauses[clause_id])
            clause["refs"] = refs_by_source.get(clause_id, [])
            result.append(clause)
        return result

    async def get_table(self, table_id: str) -> PolicyTable | None:
        return self.tables.get(table_id)


class StaticEmbedder:
    async def embed(self, ctx, texts):
        return [[0.1, 0.1, 0.1, 0.1] for _ in texts]


class StaticDenseStore:
    """按用例预设的 dense 召回结果，避免评测依赖真实向量库。"""

    def __init__(self, clause_ids: list[str]):
        self.clause_ids = clause_ids

    def search(self, tenant_id: str, policy_version: str, vector,
               limit: int = 10) -> list[dict]:
        return [
            {"clause_id": clause_id, "score": 1.0}
            for clause_id in self.clause_ids[:limit]
        ]
