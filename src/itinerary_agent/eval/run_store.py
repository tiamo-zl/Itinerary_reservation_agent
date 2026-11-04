"""评测运行落库辅助：配置快照、用例结果与汇总。"""

import subprocess
from datetime import UTC, datetime
from uuid import uuid4

from itinerary_agent.eval.suites import SuiteResult


def git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def suite_summary(results: dict[str, SuiteResult]) -> dict:
    total = sum(result.total for result in results.values())
    passed = sum(result.passed for result in results.values())
    return {
        "total_cases": total,
        "passed_cases": passed,
        "failed_cases": total - passed,
        "suite_metrics": {
            name: {
                "total": result.total,
                "passed": result.passed,
                "metrics": result.metrics,
            }
            for name, result in results.items()
        },
    }


def case_results(results: dict[str, SuiteResult],
                 cases_by_suite: dict[str, list[dict]]) -> list[dict]:
    rows: list[dict] = []
    for name, result in results.items():
        failed = {failure.get("id"): failure
                  for failure in result.failures if failure.get("id")}
        for case in cases_by_suite.get(name, []):
            case_id = case["id"]
            rows.append({
                "suite": name,
                "case_id": case_id,
                "passed": case_id not in failed,
                "detail": failed.get(case_id, {}),
            })
    return rows


def new_run(*, dataset_version: str, splits: list[str],
            suites: list[str], prompt_version: str | None,
            config: dict) -> dict:
    now = datetime.now(UTC)
    return {
        "run_id": uuid4().hex,
        "started_at": now,
        "status": "running",
        "dataset_version": dataset_version,
        "splits": sorted(splits),
        "suites": sorted(suites),
        "prompt_version": prompt_version,
        "git_sha": git_sha(),
        "config": config,
    }
