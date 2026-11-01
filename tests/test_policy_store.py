from itinerary_agent.domain.models import PolicyTable
from itinerary_agent.knowledge.policy_store import PolicyStore
from tests.db_utils import open_test_db


async def test_store_clause_edges_tables_and_fts(tmp_path):
    # 制度检索的结构化底座：条款、引用边、表格、pg_trgm 关键词召回。
    db = await open_test_db()
    store = PolicyStore(db)
    await store.init()

    await store.upsert_clause({
        "clause_id": "c1", "tenant_id": "demo-company", "doc_id": "travel-policy",
        "parent_id": "art1", "path": "travel-policy/ch3/art1/c1",
        "clause_type": "clause", "title": "住宿标准", "text": "一线城市住宿上限 500 元。",
        "table_id": "t1", "policy_version": "2026.1",
        "effective_from": "2026-01-01", "effective_to": None, "order_no": 1,
    })
    await store.upsert_clause({
        "clause_id": "c2", "tenant_id": "demo-company", "doc_id": "travel-policy",
        "parent_id": "art1", "path": "travel-policy/ch3/art1/c2",
        "clause_type": "clause", "title": "附表说明", "text": "具体标准见附表二。",
        "table_id": None, "policy_version": "2026.1",
        "effective_from": "2026-01-01", "effective_to": None, "order_no": 2,
    })
    await store.add_edge("c1", "references", "c2")
    await store.upsert_table(PolicyTable(
        table_id="t1", source_clause_id="c1", columns=["职级", "城市", "上限"],
        rows=[{"职级": "L2", "城市": "一线", "上限": 500}],
    ))

    hits = await store.keyword_search("demo-company", "2026.1", "住宿标准", limit=5)
    assert hits[0]["clause_id"] == "c1"

    expanded = await store.expand(["c1"], hops=1)
    assert "c2" in [clause["clause_id"] for clause in expanded]

    table = await store.get_table("t1")
    assert table.rows[0]["上限"] == 500
    await db.close()
