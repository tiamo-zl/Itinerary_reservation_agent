"""Judge 质量运营报告。"""

import json
from decimal import Decimal

from itinerary_agent.eval.judge_report import (
    _calibration_section,
    _dataset_stats,
    _fmt,
)


def _write_rows(path, rows):
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_dataset_stats_reports_labels_and_gaps(tmp_path):
    path = tmp_path / "dataset.jsonl"
    _write_rows(path, [
        {
            "id": "pass-a",
            "human_score": 5,
            "human_verdict": "pass",
            "label_source": "seed",
            "values": {
                "request": {"destination_city": "北京", "budget_limit": 1000},
                "options": {"flights": [], "hotels": []},
                "selected": {},
                "summary": "",
                "policy_result": {},
                "approval": {},
            },
        },
        {
            "id": "fail-b",
            "human_score": 1,
            "human_verdict": "pass",
            "label_source": "human",
            "values": {
                "request": {"destination_city": None},
                "options": {"flights": [{"price": 1}], "hotels": []},
                "selected": {"flight": {}},
                "summary": "ok",
                "policy_result": {"passed": False},
                "approval": {"status": "pending"},
            },
        },
    ])

    stats = _dataset_stats(path)
    assert stats is not None
    assert stats["total"] == 2
    assert stats["labels"] == {"pass": 2}
    assert stats["sources"] == {"seed": 1, "human": 1}
    assert stats["prefix_mismatch"] == ["fail-b"]
    assert stats["null_request_fields"]["destination_city"] == 1
    assert stats["empty_options"] == 1
    assert stats["empty_selected"] == 1
    assert stats["empty_summary"] == 1
    assert stats["missing_policy"] == 1


def test_calibration_section_without_report(tmp_path):
    lines = _calibration_section(tmp_path / "missing.json")
    assert "make judge-calibrate-human" in "\n".join(lines)


def test_calibration_section_renders_gate(tmp_path):
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps({
        "dataset": "x.jsonl",
        "label_source": {"human": 50},
        "prompt_version": "v1",
        "generated_at": "2026-11-04T00:00:00+00:00",
        "metrics": {
            "total": 50,
            "evaluated": 50,
            "agreement": 0.9,
            "mae": 0.2,
            "kappa": 0.7,
            "fail_precision": 0.9,
            "fail_recall": 0.85,
            "fail_f1": 0.87,
            "confusion": {
                "human_pass_judge_pass": 24,
                "human_pass_judge_fail": 1,
                "human_fail_judge_pass": 4,
                "human_fail_judge_fail": 21,
            },
        },
    }), encoding="utf-8")

    text = "\n".join(_calibration_section(path))
    assert "**pass**" in text
    assert "0.9000" in text
    assert "| 50/50 |" in text


def test_fmt_handles_decimal_and_none():
    assert _fmt(None) == "n/a"
    assert _fmt(Decimal("0.5")) == "0.5000"
    assert _fmt(3) == "3"
