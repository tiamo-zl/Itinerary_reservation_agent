"""Checkpoint 只读快照仓储。

供近线质量和人工复核读取 LangGraph 状态，不写 Checkpoint，
也不参与编排恢复。
"""

from itinerary_agent.infra.db import Database


class PostgresCheckpointRepository:
    def __init__(self, db: Database):
        self.db = db

    async def latest_values(self, task_id: str) -> dict | None:
        row = await self.db.fetchone(
            "SELECT checkpoint->'channel_values' AS values "
            "FROM checkpoints "
            "WHERE thread_id = ? AND checkpoint_ns = '' "
            "ORDER BY checkpoint_id DESC LIMIT 1",
            (task_id,),
        )
        if row is None or not row.get("values"):
            return None
        return dict(row["values"])
