from itinerary_agent.adapters.scripted_model import ScriptedModelGateway
from itinerary_agent.domain.models import Event, RequestContext
from itinerary_agent.infra.container import build_container
from itinerary_agent.infra.repositories.outbox_repository import (
    PostgresOutboxRepository,
)
from itinerary_agent.workers.outbox_relay import OutboxRelay
from tests.db_utils import make_test_settings, open_test_db
from tests.scenarios import PLAN, RESPOND, UNDERSTAND


class FakeTaskRepo:
    def __init__(self, task: dict):
        self.task = task

    async def get(self, task_id: str) -> dict | None:
        return self.task


class FakeOrchestrator:
    def __init__(self, task_repo: FakeTaskRepo):
        self.task_repo = task_repo
        self.calls = 0

    async def resume(self, ctx, task_id, decision):
        self.calls += 1
        self.task_repo.task = {**self.task_repo.task, "status": "WAITING_HUMAN"}
        yield Event(type="result", data={"task_id": task_id})


async def test_outbox_claim_and_mark_done(tmp_path):
    db = await open_test_db()
    repo = PostgresOutboxRepository(db)
    await repo.enqueue(
        "approval", "a1", "approval.decided", {"task_id": "t1"}
    )

    events = await repo.claim_batch(10, "worker-1", 60)
    assert len(events) == 1
    assert events[0]["payload"]["task_id"] == "t1"

    await repo.mark_done(events[0]["id"])
    assert await repo.claim_batch(10, "worker-1", 60) == []
    await db.close()


async def test_relay_resumes_task_once(tmp_path):
    db = await open_test_db()
    repo = PostgresOutboxRepository(db)
    task = {
        "task_id": "t1",
        "tenant_id": "demo-company",
        "user_id": "u001",
        "status": "WAITING_APPROVAL",
        "trace_id": "trace-1",
    }
    tasks = FakeTaskRepo(task)
    orchestrator = FakeOrchestrator(tasks)
    relay = OutboxRelay(repo, tasks, orchestrator)

    await repo.enqueue(
        "approval", "a1", "approval.decided",
        {"task_id": "t1", "status": "approved", "trace_id": "trace-1"},
    )
    event = (await repo.claim_batch(10, "worker-1", 60))[0]

    await relay._handle(event)
    # 第二次处理同一事件时任务已不在 WAITING_APPROVAL，不能重复恢复。
    await relay._handle(event)
    assert orchestrator.calls == 1
    await db.close()


async def test_admin_decision_writes_outbox_and_relay_resumes(tmp_path):
    """管理员决定与 outbox 同事务写入，relay 从 Checkpoint 恢复任务。"""
    container = build_container(make_test_settings())
    container.model = ScriptedModelGateway([UNDERSTAND, PLAN, RESPOND])
    await container.start(role="api")

    user = RequestContext(
        trace_id="trace-user", tenant_id="demo-company",
        user_id="u001", session_id="outbox-e2e",
    )
    events = [
        event async for event in container.orchestrator.start_turn(
            user, "下周二去北京出差两天，预算 1000 元"
        )
    ]
    interrupt = next(event for event in events if event.type == "interrupt")
    approval_id = interrupt.data["human_request"]["approval_id"]
    task_id = interrupt.data["task_id"]

    admin = RequestContext(
        trace_id="trace-admin", tenant_id="demo-company",
        user_id="u002", roles=["approver"], session_id="approval",
    )
    await container.approval_queries.decide(admin, approval_id, "approved", "")

    # 审批决定必须落审计，且与 outbox 同事务提交。
    audit_row = await container.db.fetchone(
        "SELECT action, decision FROM audit_log "
        "WHERE action = 'approval.decide' ORDER BY created_at DESC LIMIT 1"
    )
    assert audit_row["decision"] == "approved"

    relay = OutboxRelay(
        container.outbox_repo, container.task_repo, container.orchestrator
    )
    event = (await container.outbox_repo.claim_batch(10, "test-worker", 60))[0]
    await relay._handle(event)
    await container.outbox_repo.mark_done(event["id"])

    task = await container.task_repo.get(task_id)
    assert task["status"] == "WAITING_HUMAN"
    await container.stop()
