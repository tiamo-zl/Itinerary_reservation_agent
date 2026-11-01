"""ADAPTER_MODE=http 的端到端链路。

工具走独立 mock 依赖服务；审批提交镜像到本地投影，审批决定和
outbox 恢复保持原行为。
"""

import httpx

from itinerary_agent.adapters.http.client import JsonHttpClient
from itinerary_agent.adapters.scripted_model import ScriptedModelGateway
from itinerary_agent.domain.models import RequestContext
from itinerary_agent.infra.container import build_container
from itinerary_agent.mock_services.deps import create_deps_app
from itinerary_agent.workers.outbox_relay import OutboxRelay
from tests.db_utils import make_test_settings
from tests.scenarios import PLAN, RESPOND, UNDERSTAND


async def test_http_adapters_drive_approval_flow(tmp_path):
    settings = make_test_settings(
        adapter_mode="http", mock_deps_url="http://mock",
    )
    container = build_container(settings)
    http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_deps_app()),
        base_url="http://mock",
        timeout=2.0,
    )
    container.http_client = JsonHttpClient(
        "http://mock", timeout=2.0, max_retries=1, client=http_client,
    )
    container.model = ScriptedModelGateway([UNDERSTAND, PLAN, RESPOND])
    await container.start(role="api")

    try:
        user = RequestContext(
            trace_id="trace-http", tenant_id="demo-company",
            user_id="u001", session_id="http-e2e",
        )
        events = [
            event async for event in container.orchestrator.start_turn(
                user, "下周二去北京出差两天，预算 1000 元"
            )
        ]
        interrupt = next(
            event for event in events
            if event.type == "interrupt"
            and event.data["human_request"]["kind"] == "approval"
        )
        approval_id = interrupt.data["human_request"]["approval_id"]
        task_id = interrupt.data["task_id"]

        # HTTP 提交后本地审批投影必须可读，审批工作台才正常。
        local = await container.approval_repo.get(approval_id)
        assert local is not None

        admin = RequestContext(
            trace_id="trace-http-admin", tenant_id="demo-company",
            user_id="u002", roles=["approver"], session_id="approval",
        )
        await container.approval_queries.decide(
            admin, approval_id, "approved", "ok"
        )
        external = await container.approvals.get(approval_id)
        assert external.status.value == "approved"

        relay = OutboxRelay(
            container.outbox_repo, container.task_repo, container.orchestrator
        )
        event = (
            await container.outbox_repo.claim_batch(10, "http-worker", 60)
        )[0]
        await relay._handle(event)
        await container.outbox_repo.mark_done(event["id"])

        task = await container.task_repo.get(task_id)
        assert task["status"] == "WAITING_HUMAN"
    finally:
        await container.stop()
        await http_client.aclose()
