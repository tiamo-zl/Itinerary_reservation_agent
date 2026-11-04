"""`python -m itinerary_agent.eval.cli` 评测入口。

用法：
    uv run python -m itinerary_agent.eval.cli
    uv run python -m itinerary_agent.eval.cli --json
    uv run python -m itinerary_agent.eval.cli --suite retrieval
    uv run python -m itinerary_agent.eval.cli --record --baseline latest
    uv run python -m itinerary_agent.eval.cli --list-runs
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from itinerary_agent.eval.compare import compare_runs, render_comparison
from itinerary_agent.eval.loader import (
    DEFAULT_CASES_DIR,
    DEFAULT_THRESHOLDS,
    SPLITS,
    load_cases,
)
from itinerary_agent.eval.run_store import (
    case_results,
    new_run,
    suite_summary,
)
from itinerary_agent.eval.runner import (
    check_thresholds,
    dataset_metadata,
    load_thresholds,
    render_summary,
    run_all,
)
from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.database import Database
from itinerary_agent.infra.repositories import PostgresEvalRunRepository


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Itinerary Agent eval")
    parser.add_argument(
        "--cases-dir", type=Path, default=DEFAULT_CASES_DIR,
        help="JSONL 用例目录",
    )
    parser.add_argument(
        "--thresholds", type=Path, default=DEFAULT_THRESHOLDS,
        help="阈值 JSON",
    )
    parser.add_argument(
        "--suite", action="append", default=None,
        help="只运行指定 suite（可重复）",
    )
    parser.add_argument(
        "--split", action="append", choices=list(SPLITS), default=None,
        help="只运行指定 split（可重复）；默认 golden+regression",
    )
    parser.add_argument(
        "--json", action="store_true", help="输出机器可读 JSON",
    )
    parser.add_argument(
        "--no-enforce", action="store_true",
        help="只报告，不因阈值失败返回非零",
    )
    parser.add_argument(
        "--record", action="store_true",
        help="把运行结果写入 eval_runs / eval_case_results",
    )
    parser.add_argument(
        "--database-url", default=None,
        help="记录或对比时使用的 PostgreSQL URL；默认读 Settings",
    )
    parser.add_argument(
        "--baseline", default=None,
        help="基线 run_id，或 latest 表示最近一次同 dataset/split/suite 运行",
    )
    parser.add_argument(
        "--fail-on-regression", action="store_true",
        help="指标或用例出现 regression 时返回非零",
    )
    parser.add_argument(
        "--list-runs", action="store_true", help="列出最近评测运行",
    )
    return parser


def _serialize(results) -> dict:
    return {
        name: {
            "total": result.total,
            "passed": result.passed,
            "metrics": result.metrics,
            "failures": result.failures,
        }
        for name, result in results.items()
    }


def _config_snapshot(args, splits: set[str], suites: list[str]) -> dict:
    settings = Settings()
    return {
        "cases_dir": str(args.cases_dir),
        "thresholds": str(args.thresholds),
        "splits": sorted(splits),
        "suites": sorted(suites),
        "model_mode": settings.model_mode,
        "adapter_mode": settings.adapter_mode,
        "prompt_version": settings.prompt_version,
        "no_enforce": args.no_enforce,
    }


async def _db(args):
    url = args.database_url or Settings().database_url
    db = Database(url)
    await db.connect()
    return db


async def _list_runs(args) -> int:
    db = await _db(args)
    try:
        runs = await PostgresEvalRunRepository(db).list_recent(20)
    finally:
        await db.close()
    for run in runs:
        print(
            f"{run['run_id']}  {run['started_at']}  {run['status']:<8} "
            f"dataset={run['dataset_version']} "
            f"splits={run['splits']} suites={run['suites']} "
            f"passed={run['passed_cases']}/{run['total_cases']}"
        )
    return 0


async def _start_run(args, *, meta, splits: set[str],
                     suites: list[str]) -> str:
    db = await _db(args)
    try:
        run = new_run(
            dataset_version=meta.get("version", "unknown"),
            splits=sorted(splits),
            suites=suites,
            prompt_version=Settings().prompt_version,
            config=_config_snapshot(args, splits, suites),
        )
        await PostgresEvalRunRepository(db).create(run)
        return run["run_id"]
    finally:
        await db.close()


async def _finish_run(args, run_id: str, *, results, cases_by_suite,
                      failures: list[str]) -> dict | None:
    db = await _db(args)
    repo = PostgresEvalRunRepository(db)
    try:
        summary = suite_summary(results)
        await repo.add_case_results(
            run_id, case_results(results, cases_by_suite)
        )
        await repo.finish(
            run_id, status="failed" if failures else "passed",
            finished_at=datetime.now(UTC),
            total_cases=summary["total_cases"],
            passed_cases=summary["passed_cases"],
            failed_cases=summary["failed_cases"],
            suite_metrics=summary["suite_metrics"],
            threshold_failures=failures,
        )
        current = await repo.get(run_id)
        if not args.baseline or current is None:
            return None
        if args.baseline == "latest":
            baseline = await repo.latest_matching(
                dataset_version=current["dataset_version"],
                splits=current["splits"],
                suites=current["suites"],
                exclude_run_id=run_id,
            )
        else:
            baseline = await repo.get(args.baseline)
        if baseline is None:
            return None
        return compare_runs(
            current, baseline,
            await repo.case_results(run_id),
            await repo.case_results(baseline["run_id"]),
        )
    finally:
        await db.close()


async def _mark_error(args, run_id: str, error: str) -> None:
    db = await _db(args)
    try:
        await PostgresEvalRunRepository(db).finish(
            run_id, status="error", finished_at=datetime.now(UTC),
            total_cases=0, passed_cases=0, failed_cases=0,
            suite_metrics={}, threshold_failures=[], error=error,
        )
    finally:
        await db.close()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.list_runs:
        return asyncio.run(_list_runs(args))
    if args.baseline and not args.record:
        print("--baseline requires --record", file=sys.stderr)
        return 2

    splits = set(args.split) if args.split else {"golden", "regression"}
    meta = dataset_metadata(args.cases_dir)
    cases_by_suite = load_cases(args.cases_dir, splits=splits)
    suites = sorted(
        set(args.suite) if args.suite
        else set(cases_by_suite) - {"scenario"}
    )

    run_id = None
    if args.record:
        try:
            run_id = asyncio.run(_start_run(
                args, meta=meta, splits=splits, suites=suites,
            ))
        except Exception as exc:  # noqa: BLE001 - 记录失败不隐藏评测结果
            print(f"start run failed: {type(exc).__name__}: {exc}",
                  file=sys.stderr)

    try:
        results = asyncio.run(run_all(args.cases_dir, splits=splits))
    except Exception as exc:
        if run_id:
            asyncio.run(_mark_error(
                args, run_id, f"{type(exc).__name__}: {exc}"
            ))
        raise
    if args.suite:
        selected = set(args.suite)
        results = {
            name: result for name, result in results.items()
            if name in selected
        }
        cases_by_suite = {
            name: cases for name, cases in cases_by_suite.items()
            if name in selected
        }

    thresholds = load_thresholds(args.thresholds)
    if args.suite:
        thresholds = {
            name: value for name, value in thresholds.items()
            if name in set(args.suite)
        }
    failures = check_thresholds(results, thresholds)

    comparison = None
    if run_id:
        try:
            comparison = asyncio.run(_finish_run(
                args, run_id, results=results,
                cases_by_suite=cases_by_suite, failures=failures,
            ))
        except Exception as exc:  # noqa: BLE001 - 记录失败不隐藏评测结果
            print(f"finish run failed: {type(exc).__name__}: {exc}",
                  file=sys.stderr)

    if args.json:
        payload = {
            "dataset_version": meta.get("version", "unknown"),
            "splits": sorted(splits),
            "results": _serialize(results),
            "threshold_failures": failures,
            "passed": not failures,
        }
        if run_id:
            payload["run_id"] = run_id
        if comparison is not None:
            payload["comparison"] = comparison
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            f"dataset={meta.get('version', 'unknown')} "
            f"splits={','.join(sorted(splits))}"
        )
        print(render_summary(results))
        if failures:
            print("\n阈值未通过：")
            for failure in failures:
                print(f"  - {failure}")
        else:
            print("\nRESULT: PASS")
        if run_id:
            print(f"\nrun_id: {run_id}")
        if comparison is not None:
            print()
            print(render_comparison(comparison))
        elif args.baseline:
            print("\nno baseline run found")
    if failures and not args.no_enforce:
        return 1
    if (
        args.fail_on_regression
        and comparison is not None
        and comparison["has_regression"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
