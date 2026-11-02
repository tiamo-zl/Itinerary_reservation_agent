"""Badcase → 工单 → 结构化回归用例 → 导出的闭环。"""

import json

import pytest

from itinerary_agent.application.errors import BadRequest
from itinerary_agent.application.feedback_service import FeedbackService
from itinerary_agent.domain.models import RequestContext
from itinerary_agent.eval.badcase_export import export_badcases
from itinerary_agent.infra.repositories.feedback_repository import (
    PostgresFeedbackRepository,
)
from itinerary_agent.infra.ticketing import LocalTicketAdapter
from tests.db_utils import open_test_db


def context() -> RequestContext:
    return RequestContext(
        trace_id="trace-1", tenant_id="demo-company", user_id="u002",
        roles=["approver"], session_id="badcase",
    )


async def _service(db):
    return FeedbackService(PostgresFeedbackRepository(db), LocalTicketAdapter())


async def test_badcase_ticket_sla_and_export(tmp_path):
    db = await open_test_db()
    service = await _service(db)
    ctx = context()

    created = await service.submit(ctx, {
        "trace_id": "trace-1",
        "task_id": "task-1",
        "category": "policy",
        "severity": "high",
        "user_input": "L2 住 800 的酒店",
        "expected": "要求审批",
        "actual": "直接通过",
    })
    assert created["ticket_ref"].startswith("LOCAL-")
    assert created["sla_due_at"]

    badcase = await service.feedback_repo.get(created["badcase_id"])
    assert badcase["status"] == "open"
    assert badcase["sla_due_at"] is not None

    case = {
        "id": "replay-policy-l2-hotel-800",
        "level": "L2",
        "destination_city": "北京",
        "hotels": [{"price": 800}],
        "rules": [{
            "id": "h-l2", "match": {"employee_level": ["L2"]},
            "category": "hotel", "limit": 500, "severity": "block",
            "allow_approval": True,
        }],
        "expected_passed": False,
        "expected_requires_approval": True,
    }
    await service.update(ctx, created["badcase_id"], {
        "status": "fixed",
        "root_cause": "policy rule limit",
        "regression_suite": "policy",
        "regression_case": case,
        "owner": "u002",
    })

    output = tmp_path / "badcase_cases.jsonl"
    output.write_text(
        json.dumps({"id": "manual", "suite": "slot", "case": {"id": "manual"}})
        + "\n",
        encoding="utf-8",
    )
    wrappers = await export_badcases(
        service.feedback_repo, output, merge=True
    )
    assert len(wrappers) == 1
    wrapper = wrappers[0]
    assert wrapper["suite"] == "policy"
    assert wrapper["split"] == "regression"
    assert wrapper["source_trace_id"] == "trace-1"
    assert wrapper["case"]["id"] == "replay-policy-l2-hotel-800"

    lines = [
        json.loads(line) for line in output.read_text().splitlines()
        if line.strip()
    ]
    assert {line["id"] for line in lines} == {"manual", wrapper["id"]}
    await db.close()


async def test_closing_requires_regression_case(tmp_path):
    db = await open_test_db()
    service = await _service(db)
    ctx = context()
    created = await service.submit(ctx, {
        "trace_id": "trace-2",
        "category": "plan",
        "severity": "low",
        "user_input": "x",
    })

    with pytest.raises(BadRequest):
        await service.update(
            ctx, created["badcase_id"], {"status": "closed"}
        )

    await service.update(ctx, created["badcase_id"], {
        "regression_suite": "slot",
        "regression_case": {
            "id": "replay-slot",
            "today": "2026-10-21",
            "raw": {"destination": "北京", "departure_date": "2026-11-03"},
            "expected": {"destination_city": "北京"},
        },
        "status": "closed",
    })
    row = await service.feedback_repo.get(created["badcase_id"])
    assert row["status"] == "closed"
    await db.close()
