"""一次性 LLM judge 采样。

常驻 worker 按 `JUDGE_SAMPLE_RATE` 低频抽样；人工校准前需要一批
确定的样本，所以提供这个一次性命令：

    python -m itinerary_agent.eval.judge_sample --limit 50

它不启动 worker、不初始化 Milvus，只读取最近 COMPLETED 任务的
Checkpoint，调用 model_gateway 的 judge，并写入 judge_results。
重复任务会按 `(task_id, prompt_version)` 自动跳过。
"""

import argparse
import asyncio
import json
import sys

from itinerary_agent.eval.judge_context import CheckpointSnapshotReader
from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.database import Database
from itinerary_agent.infra.repositories import (
    PostgresJudgeRepository,
    PostgresModelCallRepository,
    PostgresTaskRepository,
)
from itinerary_agent.model_gateway.gateway import OpenAIChatGateway
from itinerary_agent.workers.llm_judge import LLMJudgeWorker


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="One-off LLM judge sampling")
    parser.add_argument("--limit", type=int, default=50,
                        help="最多评审多少个最近完成的任务")
    parser.add_argument("--lookback-minutes", type=int, default=7 * 24 * 60)
    parser.add_argument("--task-id", action="append", default=[],
                        help="只评审指定任务，可重复")
    parser.add_argument("--prompt-version", default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="只列出候选任务，不调用模型")
    return parser


async def _run(args) -> int:
    settings = Settings()
    if settings.model_mode != "live":
        print("judge sample requires MODEL_MODE=live", file=sys.stderr)
        return 2
    if not settings.deepseek_api_key:
        print("DEEPSEEK_API_KEY is required", file=sys.stderr)
        return 2

    db = Database(settings.database_url)
    await db.connect()
    model = None
    try:
        task_repo = PostgresTaskRepository(db)
        judge_repo = PostgresJudgeRepository(db)
        reader = CheckpointSnapshotReader(db)

        if args.task_id:
            fetched = await asyncio.gather(
                *(task_repo.get(task_id) for task_id in args.task_id)
            )
            tasks = [row for row in fetched if row]
            missing = len(args.task_id) - len(tasks)
            if missing:
                print(f"ignored {missing} unknown task ids", file=sys.stderr)
        else:
            tasks = await task_repo.list_recent_completed(
                args.lookback_minutes, args.limit
            )

        if args.dry_run:
            for task in tasks:
                print(task["task_id"], task["status"], task["trace_id"])
            print(f"candidates: {len(tasks)}")
            return 0

        model = OpenAIChatGateway(
            settings,
            ledger=PostgresModelCallRepository(db),
        )
        worker = LLMJudgeWorker(
            task_repo,
            judge_repo,
            reader,
            model,
            prompt_version=(
                args.prompt_version or settings.judge_prompt_version
            ),
            sample_rate=1.0,
            max_tasks=args.limit,
            lookback_minutes=args.lookback_minutes,
        )
        result = await worker.collect_once(tasks=tasks)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        if model is not None:
            await model.client.close()
            if model.fallback_client is not None:
                await model.fallback_client.close()
        await db.close()


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
