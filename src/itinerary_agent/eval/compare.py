"""两次评测运行的基线对比。

比较三件事：

- suite 指标 delta；
- 用例级 regression / fix / added / removed；
- 阈值失败变化。
"""

from typing import Any

_EPS = 1e-9


def _case_map(rows: list[dict]) -> dict[tuple[str, str], dict]:
    return {
        (row["suite"], row["case_id"]): row
        for row in rows
    }


def compare_runs(current: dict, baseline: dict,
                 current_cases: list[dict],
                 baseline_cases: list[dict]) -> dict:
    current_metrics = current.get("suite_metrics") or {}
    baseline_metrics = baseline.get("suite_metrics") or {}
    metric_changes: list[dict] = []
    for suite in sorted(set(current_metrics) | set(baseline_metrics)):
        current_suite = current_metrics.get(suite) or {}
        baseline_suite = baseline_metrics.get(suite) or {}
        current_values = current_suite.get("metrics") or {}
        baseline_values = baseline_suite.get("metrics") or {}
        for metric in sorted(set(current_values) | set(baseline_values)):
            current_value = current_values.get(metric)
            baseline_value = baseline_values.get(metric)
            delta = None
            if current_value is not None and baseline_value is not None:
                delta = float(current_value) - float(baseline_value)
            metric_changes.append({
                "suite": suite,
                "metric": metric,
                "baseline": baseline_value,
                "current": current_value,
                "delta": delta,
                "regressed": delta is not None and delta < -_EPS,
            })

    current_map = _case_map(current_cases)
    baseline_map = _case_map(baseline_cases)
    keys = set(current_map) | set(baseline_map)
    regressions: list[dict] = []
    fixes: list[dict] = []
    added: list[dict] = []
    removed: list[dict] = []
    for key in sorted(keys):
        current_case = current_map.get(key)
        baseline_case = baseline_map.get(key)
        if current_case is None and baseline_case is not None:
            removed.append(baseline_case)
        elif current_case is not None and baseline_case is None:
            added.append(current_case)
        elif (baseline_case and not baseline_case["passed"]
              and current_case and current_case["passed"]):
            fixes.append(current_case)
        elif (baseline_case and baseline_case["passed"]
              and current_case and not current_case["passed"]):
            regressions.append(current_case)

    metric_regressions = [
        change for change in metric_changes if change["regressed"]
    ]
    return {
        "current_run_id": current["run_id"],
        "baseline_run_id": baseline["run_id"],
        "dataset_version": current.get("dataset_version"),
        "baseline_dataset_version": baseline.get("dataset_version"),
        "prompt_version": current.get("prompt_version"),
        "baseline_prompt_version": baseline.get("prompt_version"),
        "git_sha": current.get("git_sha"),
        "baseline_git_sha": baseline.get("git_sha"),
        "metric_changes": metric_changes,
        "metric_regressions": metric_regressions,
        "regressions": regressions,
        "fixes": fixes,
        "added": added,
        "removed": removed,
        "threshold_failures": current.get("threshold_failures") or [],
        "baseline_threshold_failures": (
            baseline.get("threshold_failures") or []
        ),
        "has_regression": bool(metric_regressions or regressions),
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def render_comparison(comparison: dict) -> str:
    lines = [
        "Baseline comparison",
        (
            f"  baseline: {comparison['baseline_run_id']} "
            f"(dataset={comparison['baseline_dataset_version']}, "
            f"prompt={comparison['baseline_prompt_version']}, "
            f"sha={comparison['baseline_git_sha']})"
        ),
        (
            f"  current : {comparison['current_run_id']} "
            f"(dataset={comparison['dataset_version']}, "
            f"prompt={comparison['prompt_version']}, "
            f"sha={comparison['git_sha']})"
        ),
        "",
        "Metric changes:",
    ]
    for change in comparison["metric_changes"]:
        if change["delta"] is None:
            lines.append(
                f"  {change['suite']}.{change['metric']}: "
                f"{_fmt(change['baseline'])} -> {_fmt(change['current'])}"
            )
            continue
        marker = "REGRESSED" if change["regressed"] else "ok"
        lines.append(
            f"  {change['suite']}.{change['metric']}: "
            f"{_fmt(change['baseline'])} -> {_fmt(change['current'])} "
            f"({change['delta']:+.4f}) {marker}"
        )
    lines += [
        "",
        (
            f"Case changes: regressions={len(comparison['regressions'])} "
            f"fixes={len(comparison['fixes'])} "
            f"added={len(comparison['added'])} "
            f"removed={len(comparison['removed'])}"
        ),
    ]
    for row in comparison["regressions"]:
        lines.append(f"  REGRESSION {row['suite']}/{row['case_id']}")
    for row in comparison["fixes"]:
        lines.append(f"  FIX        {row['suite']}/{row['case_id']}")
    lines += [
        "",
        (
            "Threshold failures: "
            f"current={len(comparison['threshold_failures'])} "
            f"baseline={len(comparison['baseline_threshold_failures'])}"
        ),
    ]
    return "\n".join(lines)
