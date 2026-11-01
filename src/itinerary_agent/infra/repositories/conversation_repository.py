"""会话列表与详情的 SQLite 仓储。

数据来自 messages + tasks 两张表；这里只做查询组合，
“谁能看哪些会话”由 application 决定。
"""

from __future__ import annotations

from datetime import datetime

from itinerary_agent.infra.db import Database

_LATEST_TASK_SQL = (
    "SELECT t.task_id, t.trace_id, t.status, t.revision, t.updated_at "
    "FROM tasks t JOIN messages m ON m.task_id = t.task_id "
    "WHERE m.session_id = ? ORDER BY t.updated_at DESC LIMIT 1"
)


def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


class PostgresConversationRepository:
    def __init__(self, db: Database):
        self.db = db

    async def list_conversations(self, admin: bool, user_id: str,
                                  tenant_id: str, limit: int,
                                  cursor: dict | None = None) -> list[dict]:
        """会话摘要列表；员工只看自己的，管理员看本租户全部。"""
        where = "WHERE t.tenant_id = ?"
        params: list = [tenant_id]
        if not admin:
            where += " AND t.user_id = ?"
            params.append(user_id)
        having = ""
        if cursor:
            having = "HAVING (MAX(m.created_at), m.session_id) < (?, ?)"
            params.extend([
                _as_datetime(cursor["updated_at"]), cursor["session_id"],
            ])
        rows = await self.db.fetchall(
            "SELECT m.session_id, COUNT(*) AS message_count, "
            "MAX(m.created_at) AS updated_at, "
            "(SELECT content FROM messages m2 WHERE m2.session_id = m.session_id "
            " ORDER BY m2.id DESC LIMIT 1) AS last_message, "
            "(SELECT role FROM messages m2 WHERE m2.session_id = m.session_id "
            " ORDER BY m2.id DESC LIMIT 1) AS last_role, "
            "MAX(t.user_id) AS user_id, MAX(t.tenant_id) AS tenant_id "
            "FROM messages m JOIN tasks t ON t.task_id = m.task_id "
            f"{where} GROUP BY m.session_id {having} "
            "ORDER BY MAX(m.created_at) DESC, m.session_id DESC LIMIT ?",
            (*params, limit + 1),
        )
        result = []
        for row in rows:
            item = dict(row)
            item["latest_task"] = await self.latest_task(item["session_id"])
            result.append(item)
        return result

    async def list_sessions(self, user_id: str, tenant_id: str,
                            limit: int,
                            cursor: dict | None = None) -> list[dict]:
        """历史对话列表（/sessions），只返回当前员工自己的会话。"""
        having = ""
        params: list = [user_id, tenant_id]
        if cursor:
            having = "HAVING (MAX(m.created_at), m.session_id) < (?, ?)"
            params.extend([
                _as_datetime(cursor["updated_at"]), cursor["session_id"],
            ])
        rows = await self.db.fetchall(
            "SELECT m.session_id, COUNT(*) AS message_count, "
            "MAX(m.created_at) AS updated_at, "
            "(SELECT content FROM messages m2 WHERE m2.session_id = m.session_id "
            " ORDER BY m2.id DESC LIMIT 1) AS last_message, "
            "(SELECT role FROM messages m2 WHERE m2.session_id = m.session_id "
            " ORDER BY m2.id DESC LIMIT 1) AS last_role "
            "FROM messages m JOIN tasks t ON t.task_id = m.task_id "
            "WHERE t.user_id = ? AND t.tenant_id = ? GROUP BY m.session_id "
            f"{having} ORDER BY MAX(m.created_at) DESC, m.session_id DESC "
            "LIMIT ?",
            (*params, limit + 1),
        )
        result = []
        for row in rows:
            item = dict(row)
            item["latest_task"] = await self.latest_task(item["session_id"])
            result.append(item)
        return result

    async def latest_task(self, session_id: str) -> dict | None:
        row = await self.db.fetchone(_LATEST_TASK_SQL, (session_id,))
        return dict(row) if row else None

    async def list_tasks(self, session_id: str) -> list[dict]:
        """会话下的全部任务，最近的在前。"""
        rows = await self.db.fetchall(
            "SELECT DISTINCT t.task_id, t.trace_id, t.status, t.revision, "
            "t.updated_at, t.user_id, t.tenant_id "
            "FROM tasks t JOIN messages m ON m.task_id = t.task_id "
            "WHERE m.session_id = ? ORDER BY t.updated_at DESC",
            (session_id,),
        )
        return [dict(row) for row in rows]
