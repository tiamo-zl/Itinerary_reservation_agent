"""短期会话记忆与长期用户偏好。

工作记忆不在这里：它由 LangGraph Checkpoint 保存。
"""

from datetime import UTC, datetime

from itinerary_agent.domain.models import UserMemory
from itinerary_agent.infra.db import Database


class MemoryStore:
    def __init__(self, db: Database):
        self.db = db

    async def upsert(self, memory: UserMemory) -> None:
        await self.db.execute(
            "INSERT INTO user_memories (memory_id, tenant_id, user_id, kind, key, value, "
            "confidence, source_task_id, updated_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(memory_id) DO UPDATE SET value=excluded.value, "
            "confidence=excluded.confidence, updated_at=excluded.updated_at",
            (
                memory.memory_id, memory.tenant_id, memory.user_id, memory.kind,
                memory.key, memory.value, memory.confidence, memory.source_task_id,
                memory.updated_at.isoformat(),
                memory.expires_at.isoformat() if memory.expires_at else None,
            ),
        )

    async def get(self, tenant_id: str, user_id: str, kinds: list[str]) -> list[UserMemory]:
        placeholders = ",".join("?" for _ in kinds)
        rows = await self.db.fetchall(
            f"SELECT * FROM user_memories WHERE tenant_id = ? AND user_id = ? "
            f"AND kind IN ({placeholders})",
            (tenant_id, user_id, *kinds),
        )
        return [
            UserMemory(
                memory_id=row["memory_id"], tenant_id=row["tenant_id"],
                user_id=row["user_id"], kind=row["kind"], key=row["key"],
                value=row["value"], confidence=row["confidence"],
                source_task_id=row["source_task_id"],
                updated_at=datetime.fromisoformat(row["updated_at"]),
                expires_at=(
                    datetime.fromisoformat(row["expires_at"])
                    if row["expires_at"] else None
                ),
            )
            for row in rows
        ]

    async def append_message(self, session_id: str, task_id: str | None,
                             role: str, content: str) -> None:
        await self.db.execute(
            "INSERT INTO messages (session_id, task_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, task_id, role, content, datetime.now(UTC).isoformat()),
        )

    async def recent_messages(self, session_id: str, limit: int = 10) -> list[dict]:
        rows = await self.db.fetchall(
            "SELECT role, content FROM messages WHERE session_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
        return [
            {"role": row["role"], "content": row["content"]}
            for row in reversed(rows)
        ]

    async def list_messages(self, session_id: str, limit: int = 100) -> list[dict]:
        rows = await self.db.fetchall(
            "SELECT role, content, created_at FROM messages WHERE session_id = ? "
            "ORDER BY id ASC LIMIT ?",
            (session_id, limit),
        )
        return [dict(row) for row in rows]
