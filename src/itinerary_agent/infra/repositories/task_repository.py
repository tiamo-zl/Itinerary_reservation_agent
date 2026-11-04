"""任务索引仓储。

tasks 只是状态机的最小投影，完整状态在 LangGraph Checkpoint。
这里只负责读任务索引，不做权限判断。
"""

from itinerary_agent.infra.db import Database

_TASK_COLUMNS = (
    "task_id, user_id, tenant_id, status, revision, trace_id, updated_at"
)

TERMINAL_STATUSES = ("COMPLETED", "CANCELLED", "FAILED")


class PostgresTaskRepository:
    def __init__(self, db: Database):
        self.db = db

    async def list_recent(self, since_minutes: int,
                          limit: int = 100) -> list[dict]:
        """近线评估取样：最近更新过的任务。"""
        rows = await self.db.fetchall(
            f"SELECT {_TASK_COLUMNS} FROM tasks "
            "WHERE updated_at >= now() - (? * interval '1 minute') "
            "ORDER BY updated_at DESC LIMIT ?",
            (since_minutes, limit),
        )
        return [dict(row) for row in rows]

    async def list_recent_completed(self, since_minutes: int,
                                    limit: int = 100) -> list[dict]:
        """一次性 judge 采样：最近完成的任务。"""
        rows = await self.db.fetchall(
            f"SELECT {_TASK_COLUMNS} FROM tasks "
            "WHERE status = 'COMPLETED' "
            "AND updated_at >= now() - (? * interval '1 minute') "
            "ORDER BY updated_at DESC LIMIT ?",
            (since_minutes, limit),
        )
        return [dict(row) for row in rows]

    async def status_counts(self) -> list[dict]:
        """按状态聚合任务数，供业务指标投影。"""
        rows = await self.db.fetchall(
            "SELECT status, COUNT(*) AS count FROM tasks GROUP BY status"
        )
        return [dict(row) for row in rows]

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

    async def upsert(self, task_id: str, tenant_id: str, user_id: str,
                     status: str, revision: int,
                     trace_id: str | None) -> None:
        """写入/更新任务索引；完整状态仍在 Checkpoint。"""
        await self.db.execute(
            "INSERT INTO tasks (task_id, tenant_id, user_id, status, revision, "
            "trace_id, updated_at) VALUES (?, ?, ?, ?, ?, ?, now()) "
            "ON CONFLICT (task_id) DO UPDATE SET "
            "status=EXCLUDED.status, revision=EXCLUDED.revision, "
            "trace_id=EXCLUDED.trace_id, updated_at=now()",
            (task_id, tenant_id, user_id, status, revision, trace_id),
        )

    async def set_status(self, task_id: str, status: str) -> None:
        await self.db.execute(
            "UPDATE tasks SET status = ?, updated_at = now() WHERE task_id = ?",
            (status, task_id),
        )

    async def acquire_resume_lease(self, task_id: str, owner: str,
                                   lease_seconds: int) -> dict | None:
        """原子获取任务恢复租约。

        条件更新保证并发调用只有一个成功；租约过期后允许其他进程接管。
        终态任务不可恢复。返回 None 表示任务不存在、已结束或正被占用。
        """
        return await self.db.fetchone(
            "UPDATE tasks SET lease_owner = ?, "
            "lease_expires_at = now() + (? * interval '1 second'), "
            "version = version + 1, updated_at = now() "
            "WHERE task_id = ? "
            f"AND status NOT IN {TERMINAL_STATUSES} "
            "AND (lease_owner IS NULL OR lease_expires_at < now()) "
            "RETURNING task_id, version, status, tenant_id, user_id, trace_id",
            (owner, lease_seconds, task_id),
        )

    async def release_lease(self, task_id: str, owner: str) -> None:
        """释放租约；只释放自己持有的锁，避免误删他人的租约。"""
        await self.db.execute(
            "UPDATE tasks SET lease_owner = NULL, lease_expires_at = NULL, "
            "updated_at = now() WHERE task_id = ? AND lease_owner = ?",
            (task_id, owner),
        )

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
