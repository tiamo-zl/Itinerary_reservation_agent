from itinerary_agent.infra.db import Database
from itinerary_agent.observability.query import load_trace_tree


async def test_trace_tree(tmp_path):
    # parent_span_id 决定层级；根节点是 gateway.http。
    db = Database(tmp_path / "t.db")
    await db.connect()
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
    tree = await load_trace_tree(db, "t1")
    assert tree[0]["name"] == "gateway.http"
    assert tree[0]["children"][0]["name"] == "tool.search_flights"
    await db.close()
