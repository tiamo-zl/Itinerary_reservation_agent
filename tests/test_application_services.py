"""应用服务单测：注入 fake 仓储，不启动 FastAPI 或数据库。"""

import pytest

from itinerary_agent.application.errors import Forbidden, NotFound
from itinerary_agent.application.trace_queries import TraceQueryService
from itinerary_agent.domain.models import RequestContext


def context(tenant_id: str = "demo-company", user_id: str = "u001",
            roles: list[str] | None = None) -> RequestContext:
    return RequestContext(
        trace_id="trace-1",
        tenant_id=tenant_id,
        user_id=user_id,
        roles=roles or ["employee"],
        session_id="session-1",
    )


class FakeTaskRepository:
    def __init__(self, task: dict | None):
        self.task = task

    async def get(self, task_id: str) -> dict | None:
        return self.task

    async def find_by_trace(self, trace_id: str) -> dict | None:
        return self.task


class FakeTraceRepository:
    def __init__(self):
        self.calls = 0

    async def load_spans(self, trace_id: str) -> list[dict]:
        self.calls += 1
        return [
            {
                "span_id": "s1",
                "parent_span_id": None,
                "name": "gateway.http",
                "layer": "gateway",
                "status": "ok",
                "duration_ms": 1.0,
                "attributes": {},
            },
            {
                "span_id": "s2",
                "parent_span_id": "s1",
                "name": "orchestration.node.plan",
                "layer": "orchestration",
                "status": "ok",
                "duration_ms": 2.0,
                "attributes": {},
            },
        ]


async def test_get_trace_builds_tree_from_fake_repository():
    task = {"task_id": "t1", "tenant_id": "demo-company", "status": "COMPLETED"}
    trace_repo = FakeTraceRepository()
    service = TraceQueryService(trace_repo, FakeTaskRepository(task))

    detail = await service.get_trace(context(), "trace-1")

    assert detail["task_id"] == "t1"
    assert detail["task_status"] == "COMPLETED"
    assert detail["spans"][0]["children"][0]["name"] == "orchestration.node.plan"


async def test_get_trace_blocks_cross_tenant_employee():
    task = {"task_id": "t1", "tenant_id": "other-company", "status": "COMPLETED"}
    trace_repo = FakeTraceRepository()
    service = TraceQueryService(trace_repo, FakeTaskRepository(task))

    with pytest.raises(Forbidden):
        await service.get_trace(context(), "trace-1")
    # 权限判断发生在取 span 之前，避免越权读取。
    assert trace_repo.calls == 0


async def test_get_trace_allows_admin_across_tenants():
    task = {"task_id": "t1", "tenant_id": "other-company", "status": "COMPLETED"}
    service = TraceQueryService(
        FakeTraceRepository(), FakeTaskRepository(task)
    )

    detail = await service.get_trace(context(roles=["approver"]), "trace-1")
    assert detail["task_id"] == "t1"


async def test_task_query_raises_not_found():
    from itinerary_agent.application.task_queries import TaskQueryService

    class FakeOrchestration:
        async def get_state(self, task_id: str) -> dict:
            return {}

    service = TaskQueryService(FakeTaskRepository(None), FakeOrchestration())
    with pytest.raises(NotFound):
        await service.get(context(), "missing")
