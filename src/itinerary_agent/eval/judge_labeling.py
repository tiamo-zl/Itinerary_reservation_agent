"""离线 judge 校准的人工标注流程。

在线复核队列依赖真实任务；本地 demo 库可能没有足够的可评审任务。
这个工具直接以离线校准数据集为输入，分三步：

    prepare   对每个 case 跑一次 judge，生成待标注文件
    label     逐条展示 judge 输入和 judge 结论，录入人工标签
    finalize  生成 judge_calibration 可直接消费的人工标签数据集

prepare 不写入数据集的 seed 标签，避免人工标注被预置答案影响。
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from itinerary_agent.domain.models import CallContext, ModelTier
from itinerary_agent.eval.judge_calibration import _parse_judge_json
from itinerary_agent.eval.judge_format import format_context
from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.database import Database
from itinerary_agent.infra.repositories import PostgresModelCallRepository
from itinerary_agent.model_gateway.gateway import OpenAIChatGateway
from itinerary_agent.model_gateway.prompts import default_prompt_registry
from itinerary_agent.workers.llm_judge import JUDGE_SCHEMA, build_judge_payload

DEFAULT_DATASET = Path("tests/eval/judge_calibration_50.jsonl")
DEFAULT_LABELING = Path("data/judge_labeling.jsonl")
DEFAULT_HUMAN = Path("tests/eval/judge_calibration_human.jsonl")


def _read_rows(path: Path) -> list[dict]:
    rows = []
    for line_no, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    return rows


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


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


async def _judge_case(gateway: OpenAIChatGateway, case: dict,
                      prompt_version: str) -> dict:
    template = default_prompt_registry().get("judge", prompt_version)
    payload = build_judge_payload(
        case.get("task") or {"task_id": case["id"], "status": "COMPLETED"},
        case["values"],
    )
    ctx = CallContext(
        trace_id=f"labeling:{case['id']}",
        tenant_id="calibration",
        task_id=case["id"],
        purpose="judge",
        prompt_version=template.version,
    )
    completion = await gateway.complete(
        ctx,
        [
            {"role": "system", "content": template.text},
            {"role": "user", "content": json.dumps(
                payload, ensure_ascii=False
            )},
        ],
        ModelTier.STANDARD,
        response_schema=JUDGE_SCHEMA,
    )
    return _parse_judge_json(completion.text)


async def _prepare(args) -> int:
    settings = Settings()
    if settings.model_mode != "live":
        print("labeling prepare requires MODEL_MODE=live", file=sys.stderr)
        return 2
    if args.out.exists() and not args.force:
        existing = _read_rows(args.out)
        if any(row.get("human_verdict") for row in existing):
            print(
                f"{args.out} already contains human labels; "
                "use --force to overwrite",
                file=sys.stderr,
            )
            return 2
    cases = _read_rows(args.dataset)
    rows = []
    db = Database(settings.database_url)
    await db.connect()
    gateway = OpenAIChatGateway(
        settings, ledger=PostgresModelCallRepository(db)
    )
    try:
        for index, case in enumerate(cases, 1):
            if "values" not in case:
                raise ValueError(f"{case.get('id')}: missing values")
            judged = await _judge_case(
                gateway, case, args.prompt_version
            )
            rows.append({
                "id": case["id"],
                "task": case.get("task") or {
                    "task_id": case["id"], "status": "COMPLETED"
                },
                "values": case["values"],
                "judge_score": judged["score"],
                "judge_verdict": judged["verdict"],
                "judge_reason": judged["reason"],
                "human_score": None,
                "human_verdict": None,
                "comment": "",
            })
            print(
                f"[{index}/{len(cases)}] {case['id']} -> "
                f"{judged['verdict']}/{judged['score']}"
            )
    finally:
        await gateway.client.close()
        if gateway.fallback_client is not None:
            await gateway.fallback_client.close()
        await db.close()
    _write_rows(args.out, rows)
    print(f"wrote {len(rows)} rows to {args.out}")
    return 0


async def _label(args) -> int:
    rows = _read_rows(args.infile)
    labeled = skipped = 0
    for index, row in enumerate(rows, 1):
        if row.get("human_verdict") in {"pass", "fail"}:
            continue
        payload = build_judge_payload(row["task"], row["values"])
        print("\n" + "=" * 70)
        print(
            f"[{index}/{len(rows)}] {row['id']} "
            f"judge={row['judge_verdict']}/{row['judge_score']}"
        )
        print("judge reason:", row.get("judge_reason", ""))
        print(format_context(payload))
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
        row["human_verdict"] = "pass" if choice == "p" else "fail"
        row["human_score"] = score
        row["comment"] = input("comment (optional): ").strip()
        row["reviewer"] = args.reviewer
        _write_rows(args.infile, rows)
        labeled += 1
        print("  saved")
    print(f"\nlabeled {labeled}, skipped {skipped}")
    return 0


def _finalize(args) -> int:
    rows = _read_rows(args.infile)
    dataset = []
    for row in rows:
        if row.get("human_verdict") not in {"pass", "fail"}:
            continue
        if row.get("human_score") is None:
            continue
        dataset.append({
            "id": row["id"],
            "human_score": int(row["human_score"]),
            "human_verdict": row["human_verdict"],
            "label_source": "human",
            "reviewer": row.get("reviewer", ""),
            "comment": row.get("comment", ""),
            "task": row["task"],
            "values": row["values"],
            "judge_score": row.get("judge_score"),
            "judge_verdict": row.get("judge_verdict"),
            "judge_reason": row.get("judge_reason", ""),
        })
    if not dataset:
        print("no labeled rows", file=sys.stderr)
        return 2
    _write_rows(args.out, dataset)
    print(f"wrote {len(dataset)} labeled rows to {args.out}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline judge labeling")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="run judge on the dataset")
    prepare.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    prepare.add_argument("--out", type=Path, default=DEFAULT_LABELING)
    prepare.add_argument("--prompt-version", default="v1")
    prepare.add_argument("--force", action="store_true")

    label = sub.add_parser("label", help="label rows interactively")
    label.add_argument("--in", dest="infile", type=Path,
                       default=DEFAULT_LABELING)
    label.add_argument("--reviewer", default="local")

    finalize = sub.add_parser("finalize", help="emit calibration dataset")
    finalize.add_argument("--in", dest="infile", type=Path,
                          default=DEFAULT_LABELING)
    finalize.add_argument("--out", type=Path, default=DEFAULT_HUMAN)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "prepare":
        return asyncio.run(_prepare(args))
    if args.command == "label":
        return asyncio.run(_label(args))
    if args.command == "finalize":
        return _finalize(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
