"""审批单读取仓储。

审批状态流转走外部审批系统（adapters/mock/approval.py）；
这里只负责按前端需要的形状读审批单，并把任务归属字段带上。
"""

from datetime import datetime

from itinerary_agent.infra.db import Database


def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))

_APPROVAL_SQL = (
    "SELECT a.*, t.trace_id, t.user_id, t.tenant_id AS task_tenant_id, "
    "t.status AS task_status FROM approvals a "
    "LEFT JOIN tasks t ON t.task_id = a.task_id "
)


class PostgresApprovalRepository:
    def __init__(self, db: Database):
        self.db = db

    async def list_by_status(self, status: str, limit: int,
                             cursor: dict | None = None) -> list[dict]:
        where = "WHERE a.status = ?"
        params: list = [status]
        if cursor:
            where += " AND (a.created_at, a.approval_id) < (?, ?)"
            params.extend([
                _as_datetime(cursor["created_at"]), cursor["approval_id"],
            ])
        rows = await self.db.fetchall(
            _APPROVAL_SQL + f"{where} "
            "ORDER BY a.created_at DESC, a.approval_id DESC LIMIT ?",
            (*params, limit + 1),
        )
        return [dict(row) for row in rows]

    async def status_counts(self) -> list[dict]:
        """按状态聚合审批数，供业务指标投影。"""
        rows = await self.db.fetchall(
            "SELECT status, COUNT(*) AS count FROM approvals GROUP BY status"
        )
        return [dict(row) for row in rows]

    async def get(self, approval_id: str) -> dict | None:
        row = await self.db.fetchone(
            _APPROVAL_SQL + "WHERE a.approval_id = ?", (approval_id,)
        )
        return dict(row) if row else None

    async def list_for_task(self, task_id: str) -> list[dict]:
        rows = await self.db.fetchall(
            _APPROVAL_SQL + "WHERE a.task_id = ? ORDER BY a.created_at DESC",
            (task_id,),
        )
        return [dict(row) for row in rows]

    async def find_by_task_revision(self, task_id: str,
                                    revision: int) -> dict | None:
        row = await self.db.fetchone(
            "SELECT approval_id, status, comment, created_at FROM approvals "
            "WHERE task_id = ? AND revision = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (task_id, revision),
        )
        return dict(row) if row else None

    async def insert_pending(self, approval_id: str, task_id: str,
                             revision: int, payload: str,
                             created_at: str) -> int:
        return await self.db.execute(
            "INSERT INTO approvals (approval_id, task_id, revision, status, "
            "comment, payload, created_at, updated_at) "
            "VALUES (?, ?, ?, 'pending', NULL, ?, ?, ?) "
            "ON CONFLICT (task_id, revision) DO NOTHING",
            (approval_id, task_id, revision, payload, created_at, created_at),
        )

    async def decide(self, approval_id: str, status: str,
                     comment: str) -> None:
        await self.db.execute(
            "UPDATE approvals SET status = ?, comment = ?, "
            "updated_at = now(), decided_at = now() WHERE approval_id = ?",
            (status, comment, approval_id),
        )

    async def list_ready_for_resume(self) -> list[dict]:
        """任务在等待审批且审批已有结论，供轮询器兜底恢复。"""
        rows = await self.db.fetchall(
            "SELECT a.approval_id, a.task_id, a.status, t.tenant_id, "
            "t.user_id, t.trace_id FROM approvals a "
            "JOIN tasks t ON t.task_id = a.task_id "
            "WHERE t.status = 'WAITING_APPROVAL' "
            "AND a.status IN ('approved', 'rejected')"
        )
        return [dict(row) for row in rows]
