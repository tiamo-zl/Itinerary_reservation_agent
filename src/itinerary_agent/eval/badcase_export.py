"""把已 triage 的 badcase 导出为评测回归用例。

badcases 表只是 intake 副本；triage 时写入 `regression_suite` 和
`regression_case`，本工具负责合并进 `badcase_cases.jsonl`。
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.database import Database
from itinerary_agent.infra.repositories.feedback_repository import (
    PostgresFeedbackRepository,
)


def build_wrapper(row: dict) -> dict:
    case = row["regression_case"]
    if isinstance(case, str):
        case = json.loads(case)
    case = dict(case)
    case.setdefault("id", f"badcase-{row['badcase_id']}")
    return {
        "id": f"badcase-{row['badcase_id']}",
        "suite": row["regression_suite"],
        "split": "regression",
        "case": case,
        "source_trace_id": row.get("trace_id"),
    }


async def export_badcases(repo, output: Path | None = None,
                          tenant_id: str | None = None,
                          merge: bool = False) -> list[dict]:
    rows = await repo.list_regression_cases(tenant_id)
    wrappers = [build_wrapper(row) for row in rows]
    if output is None:
        return wrappers

    output.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict] = {}
    if merge and output.exists():
        for line in output.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            item = json.loads(line)
            existing[item["id"]] = item
    for wrapper in wrappers:
        existing[wrapper["id"]] = wrapper
    output.write_text(
        "".join(
            json.dumps(item, ensure_ascii=False) + "\n"
            for item in existing.values()
        ),
        encoding="utf-8",
    )
    return wrappers


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export badcase regressions")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--tenant-id", default=None)
    parser.add_argument(
        "--merge", action="store_true",
        help="与已有 badcase_cases.jsonl 按 id 合并，保留手工用例",
    )
    parser.add_argument("--json", action="store_true")
    return parser


async def _run(args) -> int:
    settings = Settings()
    db = Database(settings.database_url)
    await db.connect()
    try:
        repo = PostgresFeedbackRepository(db)
        wrappers = await export_badcases(
            repo, args.output, args.tenant_id, args.merge
        )
    finally:
        await db.close()

    if args.output is None:
        for wrapper in wrappers:
            print(json.dumps(wrapper, ensure_ascii=False))
    elif not args.json:
        print(f"exported {len(wrappers)} regression cases to {args.output}")
    if args.json:
        print(json.dumps(wrappers, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(_parser().parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
