"""在线 LLM-as-judge：采样、结构化评审与结果存储。"""

import json

from itinerary_agent.domain.models import Completion
from itinerary_agent.infra.repositories.judge_repository import (
    PostgresJudgeRepository,
)
from itinerary_agent.workers.llm_judge import (
    LLMJudgeWorker,
    build_judge_payload,
)
from tests.db_utils import open_test_db


def _state() -> dict:
    return {
        "status": "COMPLETED",
        "request": {
            "destination_city": "北京",
            "start_date": "2026-11-03",
            "need_flight": True,
            "need_hotel": True,
        },
        "options": {
            "flights": [{"airline": "东航", "price": 980, "cabin": "economy"}],
            "hotels": [{"hotel_name": "王府井酒店", "price_per_night": 480}],
        },
        "selected": {"flight_id": "f2", "hotel_id": "h1"},
        "policy_result": {"passed": True, "requires_approval": False},
        "approval": {},
        "summary": "已为您选择东航和王府井酒店。",
    }


class FakeTaskRepo:
    async def list_recent(self, since_minutes: int, limit: int):
        return [{
            "task_id": "t1", "tenant_id": "demo-company",
            "trace_id": "trace-1", "status": "COMPLETED",
        }]


class FakeOrchestrator:
    async def get_state_snapshot(self, task_id: str):
        return {"values": _state()}


class FakeJudgeRepo:
    def __init__(self):
        self.rows = []

    async def exists(self, task_id: str, prompt_version: str) -> bool:
        return any(
            row["task_id"] == task_id
            and row["prompt_version"] == prompt_version
            for row in self.rows
        )

    async def create(self, result: dict) -> None:
        self.rows.append(result)


class FakeModel:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    async def complete(self, ctx, messages, tier, response_schema=None):
        self.calls += 1
        return Completion(
            text=self.text, model="fake-judge", provider="fake"
        )


def test_build_judge_payload_scrubs_pii():
    state = _state()
    state["summary"] = "联系 13812345678"
    payload = build_judge_payload(
        {"task_id": "t1"}, state
    )
    assert "13812345678" not in json.dumps(payload, ensure_ascii=False)
    assert payload["request"]["destination_city"] == "北京"


async def test_judge_collects_structured_result():
    judge_repo = FakeJudgeRepo()
    model = FakeModel(json.dumps({
        "score": 4, "verdict": "pass", "reason": "响应完整",
    }))
    worker = LLMJudgeWorker(
        FakeTaskRepo(), judge_repo, FakeOrchestrator(), model,
        sample_rate=1.0, interval_seconds=30,
    )

    result = await worker.collect_once()

    assert result["judged"] == 1
    assert result["pass"] == 1
    assert judge_repo.rows[0]["score"] == 4
    assert judge_repo.rows[0]["verdict"] == "pass"
    assert model.calls == 1


async def test_judge_invalid_output_is_skipped():
    judge_repo = FakeJudgeRepo()
    model = FakeModel("{}")
    worker = LLMJudgeWorker(
        FakeTaskRepo(), judge_repo, FakeOrchestrator(), model,
        sample_rate=1.0, interval_seconds=30,
    )

    result = await worker.collect_once()

    assert result["judged"] == 0
    assert judge_repo.rows == []


async def test_judge_repository_deduplicates(tmp_path):
    db = await open_test_db()
    repo = PostgresJudgeRepository(db)
    row = {
        "task_id": "t1", "trace_id": "trace-1",
        "tenant_id": "demo-company", "prompt_version": "v1",
        "model": "fake", "provider": "fake", "score": 4,
        "verdict": "pass", "reason": "ok",
    }
    await repo.create(row)
    await repo.create({**row, "score": 1, "verdict": "fail"})

    assert await repo.exists("t1", "v1") is True
    assert len(await repo.list_recent()) == 1
    await db.close()
