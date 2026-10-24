"""评测集执行入口。

新增用例只需往 cases/*.jsonl 追加一行，不需要改测试代码。
"""

from datetime import date

import pytest

from itinerary_agent.control.policy import check_policy
from itinerary_agent.control.rules import PolicyRules, Rule
from itinerary_agent.domain.models import (
    HotelOption,
    SearchResults,
    TripRequest,
    UserProfile,
)
from itinerary_agent.orchestration.nodes.understand import normalize_payload
from tests import test_scenarios
from tests.eval.loader import load_cases


@pytest.mark.parametrize(
    "case", load_cases("slot_cases.jsonl"), ids=lambda case: case["id"]
)
def test_slot_cases(case):
    normalized = normalize_payload(case["raw"], today=date.fromisoformat(case["today"]))
    for key, expected in case["expected"].items():
        if key == "start_weekday":
            assert date.fromisoformat(normalized["start_date"]).weekday() == expected
        elif key == "duration_days":
            start = date.fromisoformat(normalized["start_date"])
            end = date.fromisoformat(normalized["end_date"])
            assert (end - start).days == expected
        else:
            assert normalized[key] == expected


@pytest.mark.parametrize(
    "case", load_cases("policy_cases.jsonl"), ids=lambda case: case["id"]
)
def test_policy_cases(case):
    rules = PolicyRules(
        version="2026.1",
        tenant_id="demo-company",
        defaults={},
        rules=[Rule(
            id=case["id"],
            match={"employee_level": [case["level"]]},
            category="hotel",
            limit=case["limit"],
            severity="block",
            allow_approval=case["allow_approval"],
        )],
    )
    user = UserProfile(
        user_id="u001", tenant_id="demo-company", name="tester",
        employee_level=case["level"], department="QA", city="上海",
    )
    options = SearchResults(hotels=[HotelOption(
        option_id="h1", hotel_name="H", city=case["destination_city"],
        area="中心", room_type="大床", price_per_night=case["hotel_price"],
        refundable=True, distance_to_center_km=1.0,
    )])
    result = check_policy(
        TripRequest(destination_city=case["destination_city"]), options, user, rules
    )
    assert result.passed is case["expected_passed"]
    assert result.requires_approval is case["expected_requires_approval"]


@pytest.mark.parametrize(
    "case", load_cases("scenario_cases.jsonl"), ids=lambda case: case["id"]
)
def test_scenario_manifest(case):
    # 场景清单保证评测集和端到端测试不脱节。
    assert callable(getattr(test_scenarios, case["test"]))
