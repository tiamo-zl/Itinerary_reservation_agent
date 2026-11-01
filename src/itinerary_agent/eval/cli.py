"""`python -m itinerary_agent.eval.cli` 评测入口。

用法：
    uv run python -m itinerary_agent.eval.cli
    uv run python -m itinerary_agent.eval.cli --json
    uv run python -m itinerary_agent.eval.cli --suite retrieval
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from itinerary_agent.eval.loader import DEFAULT_CASES_DIR, DEFAULT_THRESHOLDS
from itinerary_agent.eval.runner import (
    check_thresholds,
    load_thresholds,
    render_summary,
    run_all,
)


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
        "--json", action="store_true", help="输出机器可读 JSON",
    )
    parser.add_argument(
        "--no-enforce", action="store_true",
        help="只报告，不因阈值失败返回非零",
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


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    results = asyncio.run(run_all(args.cases_dir))
    if args.suite:
        results = {
            name: result for name, result in results.items()
            if name in set(args.suite)
        }

    thresholds = load_thresholds(args.thresholds)
    if args.suite:
        thresholds = {
            name: value for name, value in thresholds.items()
            if name in set(args.suite)
        }
    failures = check_thresholds(results, thresholds)

    if args.json:
        print(json.dumps({
            "results": _serialize(results),
            "threshold_failures": failures,
            "passed": not failures,
        }, ensure_ascii=False, indent=2))
    else:
        print(render_summary(results))
        if failures:
            print("\n阈值未通过：")
            for failure in failures:
                print(f"  - {failure}")
        else:
            print("\nRESULT: PASS")
    if failures and not args.no_enforce:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
