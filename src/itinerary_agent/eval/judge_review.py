"""Judge 人工复核队列：导出待复核、导入人工标签、导出 OpenJudge 配对文件。

用法：

    python -m itinerary_agent.eval.judge_review export \
        --out /tmp/judge_review.jsonl --limit 100

    # 人工填写 human_score / human_verdict / comment 后：
    python -m itinerary_agent.eval.judge_review import \
        --in /tmp/judge_review.jsonl --reviewer alice

    # 逐条人工标注（终端交互，带评审上下文）：
    python -m itinerary_agent.eval.judge_review label --limit 50

    # 生成 OpenJudge align-human 需要的配对文件：
    python -m itinerary_agent.eval.judge_review pairs \
        --out /tmp/judge_pairs.jsonl
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from itinerary_agent.eval.judge_context import (
    CheckpointSnapshotReader,
    load_judge_context,
)
from itinerary_agent.eval.judge_format import format_context
from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.database import Database
from itinerary_agent.infra.repositories.judge_repository import (
    PostgresJudgeRepository,
)


async def _with_repo(fn):
    settings = Settings()
    db = Database(settings.database_url)
    await db.connect()
    try:
        return await fn(PostgresJudgeRepository(db))
    finally:
        await db.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Judge human review queue")
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export", help="export pending judge results")
    export.add_argument("--out", type=Path, required=True)
    export.add_argument("--limit", type=int, default=100)
    export.add_argument("--verdict", choices=["pass", "fail"], default=None)
    export.add_argument("--status", default="pending")
    export.add_argument(
        "--no-context", action="store_true",
        help="do not include the judge input snapshot",
    )

    label = sub.add_parser("label", help="label pending results interactively")
    label.add_argument("--limit", type=int, default=50)
    label.add_argument("--verdict", choices=["pass", "fail"], default=None)
    label.add_argument("--reviewer", default="local")

    imp = sub.add_parser("import", help="import human labels")
    imp.add_argument("--in", dest="infile", type=Path, required=True)
    imp.add_argument("--reviewer", default="local")
    imp.add_argument("--dry-run", action="store_true")

    pairs = sub.add_parser("pairs", help="export reviewed pairs for align-human")
    pairs.add_argument("--out", type=Path, required=True)
    pairs.add_argument("--limit", type=int, default=1000)
    pairs.add_argument("--verdict", choices=["pass", "fail"], default=None)

    sub.add_parser("summary", help="show review queue counts")
    return parser


async def _export(repo, out: Path, limit: int, status: str,
                  verdict: str | None, with_context: bool = True) -> int:
    rows = await repo.list_recent(limit, status, verdict)
    reader = CheckpointSnapshotReader(repo.db) if with_context else None
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for row in rows:
            payload = {
                "judge_id": row["judge_id"],
                "task_id": row["task_id"],
                "trace_id": row["trace_id"],
                "tenant_id": row["tenant_id"],
                "prompt_version": row["prompt_version"],
                "judge_score": row["score"],
                "judge_verdict": row["verdict"],
                "judge_reason": row["reason"],
                "human_score": None,
                "human_verdict": None,
                "comment": "",
            }
            if reader is not None:
                context = await load_judge_context(reader, row)
                if context is not None:
                    payload["judge_input"] = context
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    print(f"exported {len(rows)} rows to {out}")
    return 0


def _read_labels(path: Path) -> list[dict]:
    rows = []
    for line_no, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
        rows.append(row)
    return rows


async def _import(repo, infile: Path, reviewer: str, dry_run: bool) -> int:
    rows = _read_labels(infile)
    labeled = 0
    skipped = 0
    for row in rows:
        verdict = row.get("human_verdict")
        score = row.get("human_score")
        if verdict is None or score is None:
            skipped += 1
            continue
        if verdict not in {"pass", "fail"}:
            raise ValueError(
                f"{row.get('judge_id')}: human_verdict must be pass or fail"
            )
        score = int(score)
        if not 0 <= score <= 5:
            raise ValueError(f"{row.get('judge_id')}: human_score out of range")
        if dry_run:
            labeled += 1
            continue
        if await repo.get(row["judge_id"]) is None:
            raise ValueError(f"judge_id not found: {row['judge_id']}")
        await repo.review(
            row["judge_id"], score, verdict, reviewer,
            str(row.get("comment", "")),
        )
        labeled += 1
    print(f"labeled {labeled}, skipped {skipped}")
    return 0


def _ask(prompt: str, allowed: set[str]) -> str:
    while True:
        answer = input(prompt).strip().lower()
        if answer in allowed:
            return answer
        print(f"  invalid choice: {answer or '<empty>'}")


def _ask_score() -> tuple[int | None, str]:
    while True:
        answer = input("human score 0-5 [s=skip/q=quit]: ").strip().lower()
        if answer == "s":
            return None, "skip"
        if answer == "q":
            return None, "quit"
        try:
            score = int(answer)
        except ValueError:
            print("  enter an integer 0-5")
            continue
        if 0 <= score <= 5:
            return score, "ok"
        print("  score must be between 0 and 5")


async def _label(repo, limit: int, verdict: str | None,
                 reviewer: str) -> int:
    rows = await repo.list_recent(limit, "pending", verdict)
    reader = CheckpointSnapshotReader(repo.db)
    labeled = skipped = 0
    for index, row in enumerate(rows, 1):
        context = await load_judge_context(reader, row)
        print("\n" + "=" * 70)
        print(
            f"[{index}/{len(rows)}] task={row['task_id']} "
            f"judge={row['verdict']}/{row['score']} "
            f"prompt={row['prompt_version']}"
        )
        print("judge reason:", row["reason"])
        print(format_context(context) if context else "<no checkpoint context>")
        choice = _ask(
            "human verdict [p=pass/f=fail/s=skip/q=quit]: ",
            {"p", "f", "s", "q"},
        )
        if choice == "q":
            break
        if choice == "s":
            skipped += 1
            continue
        score, action = _ask_score()
        if action == "quit":
            break
        if action == "skip":
            skipped += 1
            continue
        assert score is not None
        comment = input("comment (optional): ").strip()
        await repo.review(
            row["judge_id"], score,
            "pass" if choice == "p" else "fail", reviewer, comment,
        )
        labeled += 1
        print("  saved")
    print(f"\nlabeled {labeled}, skipped {skipped}")
    return 0


async def _pairs(repo, out: Path, limit: int, verdict: str | None) -> int:
    rows = await repo.list_recent(limit, "reviewed", verdict)
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out.open("w", encoding="utf-8") as handle:
        for row in rows:
            if row.get("human_verdict") not in {"pass", "fail"}:
                continue
            handle.write(json.dumps({
                "id": row["judge_id"],
                "judge": row["verdict"],
                "human": row["human_verdict"],
                "stratum": row.get("prompt_version") or "all",
            }, ensure_ascii=False) + "\n")
            written += 1
    print(f"wrote {written} paired rows to {out}")
    return 0


async def _summary(repo) -> int:
    rows = await repo.review_counts()
    for row in rows:
        print(f"{row['review_status']}: {row['count']}")
    return 0


async def _run(args) -> int:
    if args.command == "summary":
        return await _with_repo(_summary)
    if args.command == "export":
        return await _with_repo(
            lambda repo: _export(
                repo, args.out, args.limit, args.status, args.verdict,
                not args.no_context,
            )
        )
    if args.command == "label":
        return await _with_repo(
            lambda repo: _label(
                repo, args.limit, args.verdict, args.reviewer
            )
        )
    if args.command == "import":
        return await _with_repo(
            lambda repo: _import(repo, args.infile, args.reviewer,
                                 args.dry_run)
        )
    if args.command == "pairs":
        return await _with_repo(
            lambda repo: _pairs(repo, args.out, args.limit, args.verdict)
        )
    raise AssertionError(args.command)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
