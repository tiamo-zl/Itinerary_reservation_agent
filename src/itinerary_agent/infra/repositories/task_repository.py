"""任务索引仓储。

tasks 只是状态机的最小投影，完整状态在 LangGraph Checkpoint。
这里只负责读任务索引，不做权限判断。
"""

from itinerary_agent.infra.db import Database

_TASK_COLUMNS = (
    "task_id, user_id, tenant_id, status, revision, trace_id, updated_at"
)


class PostgresTaskRepository:
    def __init__(self, db: Database):
        self.db = db

    async def get(self, task_id: str) -> dict | None:
        """按任务 ID 读取索引行；不存在返回 None。"""
        row = await self.db.fetchone(
            f"SELECT {_TASK_COLUMNS} FROM tasks WHERE task_id = ?",
            (task_id,),
        )
        return dict(row) if row else None

    async def get_trace_id(self, task_id: str) -> str | None:
        """取任务首次请求绑定的 trace，恢复时复用它。"""
        row = await self.db.fetchone(
            "SELECT trace_id FROM tasks WHERE task_id = ?", (task_id,)
        )
        return row["trace_id"] if row else None

    async def find_by_trace(self, trace_id: str) -> dict | None:
        """按 trace 反查任务；审批轮询产生的 trace 可能没有任务。"""
        row = await self.db.fetchone(
            "SELECT task_id, user_id, tenant_id, status FROM tasks "
            "WHERE trace_id = ? ORDER BY updated_at DESC LIMIT 1",
            (trace_id,),
        )
        return dict(row) if row else None

    async def list_for_session(self, session_id: str) -> list[dict]:
        """会话 → 消息 → 任务反查，按最近更新排序。"""
        rows = await self.db.fetchall(
            "SELECT DISTINCT t.task_id, t.trace_id, t.status, t.revision, "
            "t.updated_at, t.user_id, t.tenant_id "
            "FROM tasks t JOIN messages m ON m.task_id = t.task_id "
            "WHERE m.session_id = ? ORDER BY t.updated_at DESC",
            (session_id,),
        )
        return [dict(row) for row in rows]
