"""LLM judge 校准：数据集、指标与 fake 模型路径。"""

import json
from types import SimpleNamespace

import pytest

from itinerary_agent.eval.judge_calibration import (
    DEFAULT_DATASET,
    compute_metrics,
    evaluate_cases,
    load_cases,
    render_markdown,
)


def test_seeded_dataset_shape():
    cases = load_cases(DEFAULT_DATASET)
    assert len(cases) == 24
    assert sum(c["human_verdict"] == "pass" for c in cases) == 12
    assert sum(c["human_verdict"] == "fail" for c in cases) == 12
    assert all(c["label_source"] == "seed" for c in cases)
    assert all(0 <= c["human_score"] <= 5 for c in cases)


def test_metrics_perfect_and_mixed():
    perfect = [
        {"human_score": 5, "human_verdict": "pass",
         "judge_score": 5, "judge_verdict": "pass", "error": None},
        {"human_score": 1, "human_verdict": "fail",
         "judge_score": 1, "judge_verdict": "fail", "error": None},
    ]
    metrics = compute_metrics(perfect)
    assert metrics["agreement"] == 1.0
    assert metrics["mae"] == 0.0
    assert metrics["kappa"] == 1.0
    assert metrics["fail_precision"] == 1.0
    assert metrics["fail_recall"] == 1.0

    mixed = [
        {"human_score": 5, "human_verdict": "pass",
         "judge_score": 5, "judge_verdict": "pass", "error": None},
        {"human_score": 4, "human_verdict": "pass",
         "judge_score": 1, "judge_verdict": "fail", "error": None},
        {"human_score": 1, "human_verdict": "fail",
         "judge_score": 4, "judge_verdict": "pass", "error": None},
        {"human_score": 0, "human_verdict": "fail",
         "judge_score": 0, "judge_verdict": "fail", "error": None},
        {"human_score": 3, "human_verdict": "pass",
         "judge_score": None, "judge_verdict": None,
         "error": "timeout"},
    ]
    metrics = compute_metrics(mixed)
    assert metrics["total"] == 5
    assert metrics["evaluated"] == 4
    assert metrics["errors"] == 1
    assert metrics["agreement"] == 0.5
    assert metrics["mae"] == pytest.approx(1.5)
    assert metrics["fail_precision"] == 0.5
    assert metrics["fail_recall"] == 0.5
    assert metrics["fail_f1"] == 0.5


def test_metrics_all_errors():
    metrics = compute_metrics([
        {"human_score": 5, "human_verdict": "pass",
         "judge_score": None, "judge_verdict": None, "error": "boom"},
    ])
    assert metrics["evaluated"] == 0
    assert metrics["agreement"] is None
    assert metrics["kappa"] is None


@pytest.mark.asyncio
async def test_evaluate_cases_with_fake_model():
    cases = load_cases(DEFAULT_DATASET)[:2]

    class FakeModel:
        async def complete(self, ctx, messages, tier, *, response_schema=None):
            assert ctx.purpose == "judge"
            assert messages[0]["role"] == "system"
            return SimpleNamespace(
                text=json.dumps({
                    "score": 5, "verdict": "pass", "reason": "ok",
                }),
                model="fake-model", provider="fake",
            )

    results = await evaluate_cases(cases, FakeModel())
    assert len(results) == 2
    assert all(r["error"] is None for r in results)
    assert all(r["judge_verdict"] == "pass" for r in results)
    assert all(r["model"] == "fake-model" for r in results)

    markdown = render_markdown(
        cases, results, compute_metrics(results),
        dataset=DEFAULT_DATASET, prompt_version="v1",
    )
    assert "LLM-as-judge 校准报告" in markdown
    assert "seeded" in markdown.lower()
