from itinerary_agent.domain.models import (
    PolicyClause,
    PolicyContext,
    PolicyTable,
)
from itinerary_agent.infra.db import Database
from itinerary_agent.knowledge.policy_store import PolicyStore
from itinerary_agent.knowledge.service import KnowledgeService


class FakeEmbedder:
    async def embed(self, ctx, texts):
        return [[0.1] * 1024 for _ in texts]


class FakeDenseStore:
    def __init__(self, clause_ids):
        self.clause_ids = clause_ids

    def search(self, tenant_id, policy_version, vector, limit=10):
        return [
            {"clause_id": clause_id, "score": 1.0}
            for clause_id in self.clause_ids[:limit]
        ]


async def _make_store(tmp_path):
    db = Database(tmp_path / "r.db")
    await db.connect()
    store = PolicyStore(db)
    await store.init()
    for clause_id, text, table_id in [
        ("c1", "一线城市住宿上限 500 元，具体见附表二。", "t1"),
        ("c2", "附表二给出各职级标准。", "t1"),
        ("c3", "紧急会议可特批。", None),
    ]:
        await store.upsert_clause({
            "clause_id": clause_id, "tenant_id": "demo-company",
            "doc_id": "travel-policy", "parent_id": None,
            "path": f"travel-policy/{clause_id}", "clause_type": "clause",
            "title": clause_id, "text": text, "table_id": table_id,
            "policy_version": "2026.1", "effective_from": "2026-01-01",
            "effective_to": None, "order_no": int(clause_id[1:]),
        })
    await store.add_edge("c1", "references", "c2")
    await store.add_edge("c1", "exception_to", "c3")
    await store.upsert_table(PolicyTable(
        table_id="t1", source_clause_id="c1", columns=["职级", "上限"],
        rows=[{"职级": "L2", "上限": 500}],
    ))
    return db, store


async def test_context_pack_expands_references_and_table(tmp_path):
    db, store = await _make_store(tmp_path)
    service = KnowledgeService(
        embedder=FakeEmbedder(), policy_store=store,
        dense_store=FakeDenseStore(["c1"]), policy_version="2026.1",
        seed_top_k=8, graph_hops=1, max_expanded_clauses=20,
    )
    ctx = type("Ctx", (), {"trace_id": "t", "tenant_id": "demo-company"})()
    result = await service.search_policy(ctx, "一线城市住宿")

    ids = [clause.clause_id for clause in result.clauses]
    assert "c1" in ids and "c2" in ids and "c3" in ids
    assert result.tables[0].table_id == "t1"
    assert result.insufficient is False
    await db.close()


async def test_insufficient_when_table_missing(tmp_path):
    db, store = await _make_store(tmp_path)
    await store.upsert_clause({
        "clause_id": "c4", "tenant_id": "demo-company", "doc_id": "travel-policy",
        "parent_id": None, "path": "travel-policy/c4", "clause_type": "clause",
        "title": "缺失表格", "text": "具体见附表九。", "table_id": "missing",
        "policy_version": "2026.1", "effective_from": "2026-01-01",
        "effective_to": None, "order_no": 4,
    })
    service = KnowledgeService(
        embedder=FakeEmbedder(), policy_store=store,
        dense_store=FakeDenseStore(["c4"]), policy_version="2026.1",
        seed_top_k=8, graph_hops=1, max_expanded_clauses=20,
    )
    ctx = type("Ctx", (), {"trace_id": "t", "tenant_id": "demo-company"})()
    result = await service.search_policy(ctx, "附表九")
    assert result.insufficient is True
    await db.close()


class FakeKnowledge:
    async def search_policy(self, ctx, query, filters=None):
        return PolicyContext(
            clauses=[PolicyClause(
                clause_id="c1", path="p/c1", title="住宿标准", text="上限 500",
                clause_type="clause", policy_version="2026.1",
            )],
            tables=[], citations=["c1"], policy_version="2026.1",
        )


async def test_plan_uses_context_refs():
    from langgraph.checkpoint.memory import MemorySaver

    from tests.fakes import ScriptedDeps

    deps = ScriptedDeps(checkpointer=MemorySaver())
    deps.knowledge = FakeKnowledge()
    service = deps.build_service()
    ctx = type("Ctx", (), {
        "trace_id": "t", "tenant_id": "demo-company", "user_id": "u001",
        "session_id": "s", "roles": [],
    })()
    events = [event async for event in service.start_turn(ctx, "去北京出差")]
    state = await service.graph.aget_state(
        {"configurable": {"thread_id": events[0].data["task_id"]}}
    )
    assert state.values["policy_refs"] == ["c1"]
