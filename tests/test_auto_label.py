"""确定性 silver label 规则。"""

import json
from pathlib import Path

from itinerary_agent.eval.auto_label import auto_label

DATASET = Path("tests/eval/judge_calibration_50.jsonl")


def _case(case_id: str) -> dict:
    for line in DATASET.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row["id"] == case_id:
                return row
    raise AssertionError(case_id)


def test_auto_label_reproduces_seed_50():
    for line in DATASET.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        label = auto_label(row["values"])
        assert label["verdict"] == row["human_verdict"], row["id"]


def test_auto_label_flags_budget_overrun():
    label = auto_label(_case("fail-budget-overrun")["values"])
    assert label["verdict"] == "fail"
    assert any("exceeds budget" in reason for reason in label["reasons"])


def test_auto_label_flags_policy_contradiction():
    label = auto_label(_case("fail-policy-contradiction")["values"])
    assert label["verdict"] == "fail"
    assert any("despite violations" in reason for reason in label["reasons"])


def test_auto_label_allows_single_day_round_trip():
    label = auto_label(_case("pass-single-day")["values"])
    assert label["verdict"] == "pass"
