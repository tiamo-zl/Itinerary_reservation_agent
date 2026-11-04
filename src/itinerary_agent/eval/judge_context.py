"""读取任务 Checkpoint，还原 judge 输入上下文。

在线 judge 只保存结构化结果，不保存评审输入。人工复核需要看到
当时送给 judge 的 request/options/selected/policy/summary，才能在
不打开完整对话的前提下独立判断。这里直接读取最新 Checkpoint，
避免为复核启动整个编排图。
"""

from itinerary_agent.infra.db import Database
from itinerary_agent.infra.repositories import PostgresCheckpointRepository
from itinerary_agent.workers.llm_judge import build_judge_payload


class CheckpointSnapshotReader:
    """最小只读快照读取器，接口与 Orchestrator.get_state_snapshot 一致。"""

    def __init__(self, db: Database):
        self.repo = PostgresCheckpointRepository(db)

    async def get_state_snapshot(self, task_id: str) -> dict:
        values = await self.repo.latest_values(task_id) or {}
        return {"values": values, "next": []}


async def load_judge_context(
    reader: CheckpointSnapshotReader, task: dict
) -> dict | None:
    """返回与在线 judge 相同的输入结构；任务没有 Checkpoint 时返回 None。"""
    snapshot = await reader.get_state_snapshot(task["task_id"])
    values = snapshot.get("values") or {}
    if not values:
        return None
    return build_judge_payload(task, values)
