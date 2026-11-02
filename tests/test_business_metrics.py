"""业务 KPI 投影：PostgreSQL 状态聚合到 Prometheus gauge。"""

from datetime import UTC, datetime

from itinerary_agent.infra.repositories.approval_repository import (
    PostgresApprovalRepository,
)
from itinerary_agent.infra.repositories.feedback_repository import (
    PostgresFeedbackRepository,
)
from itinerary_agent.infra.repositories.task_repository import (
    PostgresTaskRepository,
)
from itinerary_agent.workers.business_metrics import (
    APPROVAL_STATUS,
    BADCASE_RATE,
    BADCASE_STATUS,
    TASK_COMPLETION_RATIO,
    TASK_STATUS,
    BusinessMetricsWorker,
)
from tests.db_utils import open_test_db


async def test_business_metrics_projection(tmp_path):
    db = await open_test_db()
    tasks = PostgresTaskRepository(db)
    approvals = PostgresApprovalRepository(db)
    badcases = PostgresFeedbackRepository(db)

    for task_id, status in [
        ("t1", "COMPLETED"), ("t2", "COMPLETED"),
        ("t3", "WAITING_APPROVAL"), ("t4", "FAILED"),
    ]:
        await tasks.upsert(
            task_id, "demo-company", "u001", status, 0, None
        )

    now = datetime.now(UTC).isoformat()
    await approvals.insert_pending("a1", "t3", 0, "{}", now)
    await approvals.insert_pending("a2", "t1", 0, "{}", now)
    await approvals.decide("a2", "approved", "ok")

    await badcases.create({
        "badcase_id": "b1", "trace_id": "trace-1", "task_id": "t1",
        "tenant_id": "demo-company", "category": "plan", "severity": "high",
        "user_input": "", "expected": "", "actual": "", "comment": "",
        "status": "open", "created_at": now, "updated_at": now,
    })
    await badcases.create({
        "badcase_id": "b2", "trace_id": "trace-2", "task_id": "t2",
        "tenant_id": "demo-company", "category": "plan", "severity": "low",
        "user_input": "", "expected": "", "actual": "", "comment": "",
        "status": "fixed", "created_at": now, "updated_at": now,
    })

    worker = BusinessMetricsWorker(tasks, approvals, badcases, 60)
    snapshot = await worker.collect_once()

    assert snapshot["total_tasks"] == 4
    assert TASK_STATUS.labels(status="COMPLETED")._value.get() == 2
    assert TASK_STATUS.labels(status="FAILED")._value.get() == 1
    assert APPROVAL_STATUS.labels(status="pending")._value.get() == 1
    assert APPROVAL_STATUS.labels(status="approved")._value.get() == 1
    assert BADCASE_STATUS.labels(status="open")._value.get() == 1
    assert TASK_COMPLETION_RATIO._value.get() == 0.5
    assert BADCASE_RATE._value.get() == 250.0
    await db.close()
