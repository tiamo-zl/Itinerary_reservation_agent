"""Judge 结果的人工复核队列。"""

import pytest

from itinerary_agent.application.errors import BadRequest
from itinerary_agent.application.quality_queries import QualityQueryService
from itinerary_agent.domain.models import RequestContext
from itinerary_agent.infra.repositories.judge_repository import (
    PostgresJudgeRepository,
)
from tests.db_utils import open_test_db


def admin_ctx():
    return RequestContext(
        trace_id="review-trace", tenant_id="demo-company", user_id="u002",
        roles=["approver"], session_id="review",
    )


async def _create(repo, task_id="task-review"):
    await repo.create({
        "task_id": task_id,
        "trace_id": "trace-review",
        "tenant_id": "demo-company",
        "prompt_version": "v1",
        "model": "fake",
        "provider": "fake",
        "score": 2,
        "verdict": "fail",
        "reason": "missing summary",
    })
    rows = await repo.list_recent(10, "pending")
    return rows[0]["judge_id"]


async def test_judge_review_queue():
    db = await open_test_db()
    repo = PostgresJudgeRepository(db)
    judge_id = await _create(repo)

    pending = await repo.list_recent(10, "pending", "fail")
    assert any(row["judge_id"] == judge_id for row in pending)
    assert pending[0]["review_status"] == "pending"

    await repo.review(judge_id, 4, "pass", "reviewer-a", "ok")
    row = await repo.get(judge_id)
    assert row["review_status"] == "reviewed"
    assert row["human_score"] == 4
    assert row["human_verdict"] == "pass"
    assert row["reviewer"] == "reviewer-a"

    counts = {row["review_status"]: row["count"]
              for row in await repo.review_counts()}
    assert counts["reviewed"] == 1
    await db.close()


async def test_quality_service_reviews_and_validates():
    db = await open_test_db()
    repo = PostgresJudgeRepository(db)
    judge_id = await _create(repo, "task-review-service")
    service = QualityQueryService(finding_repo=None, judge_repo=repo)

    result = await service.review_judgement(
        admin_ctx(), judge_id, 5, "pass", "human agrees"
    )
    assert result["ok"] is True
    assert result["judgement"]["human_score"] == 5

    with pytest.raises(BadRequest):
        await service.review_judgement(
            admin_ctx(), judge_id, 9, "pass", ""
        )
    await db.close()


async def test_judge_review_api(tmp_path):
    from fastapi.testclient import TestClient

    from tests.scenarios import make_app

    db = await open_test_db()
    repo = PostgresJudgeRepository(db)
    judge_id = await _create(repo, "task-review-api")
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        listed = client.get(
            "/quality/judgements?review_status=pending",
            headers={"X-Mock-User": "u002"},
        )
        assert listed.status_code == 200
        assert any(
            row["judge_id"] == judge_id
            for row in listed.json()["judgements"]
        )
        reviewed = client.patch(
            f"/quality/judgements/{judge_id}",
            headers={"X-Mock-User": "u002"},
            json={
                "human_score": 5,
                "human_verdict": "pass",
                "comment": "api review",
            },
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["judgement"]["human_verdict"] == "pass"
    await db.close()
