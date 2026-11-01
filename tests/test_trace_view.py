from itinerary_agent.infra.repositories.trace_repository import (
    PostgresTraceRepository,
)
from itinerary_agent.observability.query import build_trace_tree
from tests.db_utils import open_test_db


async def test_trace_tree(tmp_path):
    # parent_span_id 决定层级；根节点是 gateway.http。
    db = await open_test_db()
    await db.execute(
        "INSERT INTO spans (span_id, trace_id, parent_span_id, name, layer, status, "
        "start_time, duration_ms, attributes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("s1", "t1", None, "gateway.http", "gateway", "ok",
         "2026-10-21T00:00:00+00:00", 1.0, "{}"),
    )
    await db.execute(
        "INSERT INTO spans (span_id, trace_id, parent_span_id, name, layer, status, "
        "start_time, duration_ms, attributes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("s2", "t1", "s1", "tool.search_flights", "tools", "ok",
         "2026-10-21T00:00:01+00:00", 2.0, "{}"),
    )
    # 仓储负责 SQL 与 attributes 反序列化，树形重建是纯函数。
    spans = await PostgresTraceRepository(db).load_spans("t1")
    tree = build_trace_tree(spans)
    assert tree[0]["name"] == "gateway.http"
    assert tree[0]["children"][0]["name"] == "tool.search_flights"
    await db.close()
