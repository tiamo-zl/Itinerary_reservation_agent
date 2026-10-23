from itinerary_agent.infra.db import Database
from itinerary_agent.observability.tracing import TraceRecorder


async def test_span_is_persisted(tmp_path):
    db = Database(tmp_path / "trace.db")
    await db.connect()
    recorder = TraceRecorder(db)
    trace_id = recorder.start_trace()
    async with recorder.span("gateway.http", layer="gateway", status_code=200):
        pass
    rows = await db.fetchall(
        "SELECT name, layer, status FROM spans WHERE trace_id = ?", (trace_id,)
    )
    assert rows[0]["name"] == "gateway.http"
    assert rows[0]["layer"] == "gateway"
    assert rows[0]["status"] == "ok"
    await db.close()
