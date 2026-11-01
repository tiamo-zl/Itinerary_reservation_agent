"""审批单读取仓储。

审批状态流转走外部审批系统（adapters/mock/approval.py）；
这里只负责按前端需要的形状读审批单，并把任务归属字段带上。
"""

from itinerary_agent.infra.db import Database

_APPROVAL_SQL = (
    "SELECT a.*, t.trace_id, t.user_id, t.tenant_id AS task_tenant_id, "
    "t.status AS task_status FROM approvals a "
    "LEFT JOIN tasks t ON t.task_id = a.task_id "
)


class PostgresApprovalRepository:
    def __init__(self, db: Database):
        self.db = db

    async def list_by_status(self, status: str, limit: int) -> list[dict]:
        rows = await self.db.fetchall(
            _APPROVAL_SQL + "WHERE a.status = ? ORDER BY a.created_at DESC LIMIT ?",
            (status, limit),
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
