"""评测执行器与阈值判定。"""

from pathlib import Path

from itinerary_agent.eval.loader import (
    DEFAULT_CASES_DIR,
    DEFAULT_THRESHOLDS,
    load_cases,
    load_dataset,
    load_json,
)
from itinerary_agent.eval.suites import (
    SuiteResult,
    evaluate_approval,
    evaluate_badcases,
    evaluate_policy,
    evaluate_prompts,
    evaluate_retrieval,
    evaluate_slots,
    load_retrieval_kb,
)


async def run_all(
    cases_dir: Path = DEFAULT_CASES_DIR,
    splits: set[str] | None = None,
) -> dict[str, SuiteResult]:
    if splits is None:
        splits = {"golden", "regression"}
    cases = load_cases(cases_dir, splits=splits)
    kb = load_retrieval_kb(cases_dir)
    results = {
        "slot": evaluate_slots(cases["slot"]),
        "policy": evaluate_policy(cases["policy"]),
        "retrieval": await evaluate_retrieval(cases["retrieval"], kb),
        "approval": evaluate_approval(cases["approval"]),
        "prompt": evaluate_prompts(cases["prompt"]),
        "badcase": await evaluate_badcases(cases["badcase"], cases_dir),
    }
    return results


def check_thresholds(results: dict[str, SuiteResult],
                     thresholds: dict) -> list[str]:
    """返回全部未达标的 (suite.metric) 说明；空列表表示通过。"""
    failures: list[str] = []
    for suite, required in thresholds.items():
        if suite not in results:
            failures.append(f"{suite}: suite missing")
            continue
        result = results[suite]
        if result.total == 0:
            # split 过滤后某些 suite 为空是正常情况。
            continue
        for metric, minimum in required.items():
            actual = result.metrics.get(metric)
            if actual is None:
                failures.append(f"{suite}.{metric}: metric missing")
            elif actual + 1e-9 < float(minimum):
                failures.append(
                    f"{suite}.{metric}: {actual:.4f} < {float(minimum):.4f}"
                )
    return failures


def load_thresholds(path: Path = DEFAULT_THRESHOLDS) -> dict:
    return load_json(path)


def dataset_metadata(cases_dir: Path = DEFAULT_CASES_DIR) -> dict:
    return load_dataset(cases_dir)


def render_summary(results: dict[str, SuiteResult]) -> str:
    lines = [
        f"{'suite':<12}{'cases':>7}{'passed':>8}  metrics",
        "-" * 72,
    ]
    for name, result in results.items():
        metrics = ", ".join(
            f"{key}={value:.4f}" for key, value in result.metrics.items()
        )
        lines.append(
            f"{name:<12}{result.total:>7}{result.passed:>8}  {metrics}"
        )
    return "\n".join(lines)
