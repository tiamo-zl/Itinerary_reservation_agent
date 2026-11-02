"""近线质量评估：状态检查、抽样与 finding 去重。"""

from itinerary_agent.infra.repositories.quality_repository import (
    PostgresQualityFindingRepository,
)
from itinerary_agent.workers.quality_eval import (
    QualityEvalWorker,
    evaluate_state,
)
from tests.db_utils import open_test_db


def _completed_state() -> dict:
    return {
        "status": "COMPLETED",
        "request": {
            "destination_city": "北京",
            "need_flight": True,
            "need_hotel": True,
        },
        "options": {
            "flights": [{"option_id": "f1"}],
            "hotels": [{"option_id": "h1"}],
        },
        "selected": {"flight_id": "f1", "hotel_id": "h1"},
        "policy_result": {"passed": True, "requires_approval": False},
        "approval": {"status": "approved"},
        "pending_human": None,
        "error": None,
    }


def test_evaluate_completed_state_passes():
    findings = evaluate_state(
        {"task_id": "t1", "status": "COMPLETED"}, _completed_state()
    )
    assert findings
    assert all(finding["status"] == "pass" for finding in findings)


def test_evaluate_finds_missing_slot_and_options():
    state = _completed_state()
    state["request"]["destination_city"] = None
    state["options"] = {"flights": [], "hotels": []}
    state["selected"] = {}
    findings = {
        item["check_name"]: item["status"]
        for item in evaluate_state({"task_id": "t1"}, state)
    }
    assert findings["slot_complete"] == "fail"
    assert findings["options_available"] == "fail"
    assert findings["booking_consistent"] == "fail"


def test_evaluate_missing_checkpoint_state():
    findings = evaluate_state({"task_id": "t1"}, {})
    assert findings == [{
        "check_name": "state_available",
        "status": "fail",
        "detail": "checkpoint state is missing",
    }]


class FakeTaskRepo:
    def __init__(self, tasks):
        self.tasks = tasks

    async def list_recent(self, since_minutes: int, limit: int):
        return self.tasks


class FakeOrchestrator:
    def __init__(self, states):
        self.states = states

    async def get_state_snapshot(self, task_id: str):
        return {"values": self.states.get(task_id, {})}


class FakeFindings:
    def __init__(self):
        self.rows = []

    async def upsert_many(self, findings):
        self.rows.extend(findings)


async def test_worker_samples_and_writes_findings():
    tasks = [
        {"task_id": "t1", "tenant_id": "demo-company", "trace_id": "trace-1"},
        {"task_id": "t2", "tenant_id": "demo-company", "trace_id": "trace-2"},
    ]
    findings = FakeFindings()
    worker = QualityEvalWorker(
        FakeTaskRepo(tasks),
        findings,
        FakeOrchestrator({"t1": _completed_state(), "t2": {}}),
        sample_rate=1.0,
        interval_seconds=60,
    )

    result = await worker.collect_once()

    assert result["sampled"] == 2
    assert result["findings"] > 0
    assert any(row["check_name"] == "state_available"
               for row in findings.rows)


async def test_finding_upsert_is_idempotent(tmp_path):
    db = await open_test_db()
    repo = PostgresQualityFindingRepository(db)
    row = {
        "task_id": "t1", "trace_id": "trace-1", "tenant_id": "demo-company",
        "check_name": "slot_complete", "status": "fail", "detail": "missing",
    }
    await repo.upsert_many([row])
    await repo.upsert_many([{**row, "status": "pass", "detail": ""}])

    rows = await repo.list_recent()
    assert len(rows) == 1
    assert rows[0]["status"] == "pass"
    await db.close()
