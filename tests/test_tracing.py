from itinerary_agent.infra.repositories import PostgresSpanRepository
from itinerary_agent.observability.tracing import TraceRecorder
from tests.db_utils import open_test_db


async def test_span_is_persisted(tmp_path):
    # 验证 span 会落到 PostgreSQL，并且 layer/status 能被查询到。
    db = await open_test_db()
    recorder = TraceRecorder(PostgresSpanRepository(db))
    trace_id = recorder.start_trace()
    async with recorder.span("gateway.http", layer="gateway", status_code=200):
        pass
    rows = await db.fetchall(
        "SELECT name, layer, status, attributes FROM spans "
        "WHERE trace_id = ?",
        (trace_id,),
    )
    assert rows[0]["name"] == "gateway.http"
    assert rows[0]["layer"] == "gateway"
    assert rows[0]["status"] == "ok"
    attrs = rows[0]["attributes"]
    if isinstance(attrs, str):
        import json
        attrs = json.loads(attrs)
    assert attrs["app.trace_id"] == trace_id
    await db.close()
