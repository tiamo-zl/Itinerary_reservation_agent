"""游标分页：按 (时间, ID) keyset 翻页，不重复不遗漏。"""

import pytest
from fastapi.testclient import TestClient

from itinerary_agent.application.errors import BadRequest
from itinerary_agent.application.pagination import normalize_limit
from itinerary_agent.application.trace_queries import TraceQueryService
from itinerary_agent.domain.models import RequestContext
from itinerary_agent.infra.repositories.trace_repository import (
    PostgresTraceRepository,
)
from tests.db_utils import open_test_db
from tests.scenarios import make_app


class FakeTaskRepository:
    async def get(self, task_id: str):
        return None

    async def find_by_trace(self, trace_id: str):
        return None


def _ctx() -> RequestContext:
    return RequestContext(
        trace_id="t", tenant_id="demo-company", user_id="u001",
        session_id="s", roles=["employee"],
    )


async def test_trace_pagination_uses_keyset_cursor(tmp_path):
    db = await open_test_db()
    for index, trace_id in enumerate(["t1", "t2", "t3"], start=1):
        await db.execute(
            "INSERT INTO spans (span_id, trace_id, name, layer, status, "
            "start_time, duration_ms, attributes) VALUES "
            f"('{trace_id}-s', '{trace_id}', 'gateway', 'gateway', 'ok', "
            f"now() - interval '{index} minutes', 1, '{{}}')"
        )

    service = TraceQueryService(
        PostgresTraceRepository(db), FakeTaskRepository()
    )
    first = await service.list_traces(_ctx(), limit=2)
    assert [item["trace_id"] for item in first["traces"]] == ["t1", "t2"]
    assert first["next_cursor"]

    second = await service.list_traces(
        _ctx(), limit=2, cursor=first["next_cursor"]
    )
    assert [item["trace_id"] for item in second["traces"]] == ["t3"]
    assert second["next_cursor"] is None

    # 损坏的游标必须是 400，而不是静默从头开始。
    with pytest.raises(BadRequest):
        await service.list_traces(_ctx(), limit=2, cursor="not-a-cursor")
    await db.close()


def test_invalid_cursor_returns_400_over_http(tmp_path):
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/traces?cursor=not-a-cursor")
    assert response.status_code == 400
    assert response.json()["code"] == "BAD_REQUEST"


def test_limit_is_capped():
    assert normalize_limit(0) == 1
    assert normalize_limit(10_000) == 200
    assert normalize_limit("abc") == 50
