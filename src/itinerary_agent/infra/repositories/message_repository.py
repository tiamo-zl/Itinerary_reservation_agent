"""会话消息仓储。"""

from itinerary_agent.infra.db import Database


class PostgresMessageRepository:
    def __init__(self, db: Database):
        self.db = db

    async def append(self, session_id: str, task_id: str | None,
                     role: str, content: str) -> None:
        await self.db.execute(
            "INSERT INTO messages (session_id, task_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?, now())",
            (session_id, task_id, role, content),
        )

    async def recent(self, session_id: str, limit: int = 10) -> list[dict]:
        rows = await self.db.fetchall(
            "SELECT role, content FROM messages WHERE session_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
        return [dict(row) for row in reversed(rows)]

    async def list(self, session_id: str, limit: int = 100) -> list[dict]:
        rows = await self.db.fetchall(
            "SELECT role, content, task_id, created_at FROM messages "
            "WHERE session_id = ? ORDER BY id ASC LIMIT ?",
            (session_id, limit),
        )
        return [dict(row) for row in rows]
