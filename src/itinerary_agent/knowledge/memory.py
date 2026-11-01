"""短期会话记忆与长期用户偏好。

SQL 已下沉到 infra/repositories；这里只做领域映射与组合。
"""

from datetime import datetime
from typing import Protocol

from itinerary_agent.domain.models import UserMemory


class MessageStorePort(Protocol):
    async def append(self, session_id: str, task_id: str | None,
                     role: str, content: str) -> None: ...
    async def recent(self, session_id: str, limit: int) -> list[dict]: ...
    async def list(self, session_id: str, limit: int) -> list[dict]: ...


class MemoryStorePort(Protocol):
    async def upsert(self, memory: UserMemory) -> None: ...
    async def get(self, tenant_id: str, user_id: str,
                  kinds: list[str]) -> list[dict]: ...


def _as_datetime(value) -> datetime:
    """PostgreSQL 返回 datetime；兼容旧数据的 ISO 字符串。"""
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


class MemoryStore:
    def __init__(self, messages: MessageStorePort,
                 memories: MemoryStorePort):
        self.messages = messages
        self.memories = memories

    async def upsert(self, memory: UserMemory) -> None:
        await self.memories.upsert(memory)

    async def get(self, tenant_id: str, user_id: str,
                  kinds: list[str]) -> list[UserMemory]:
        rows = await self.memories.get(tenant_id, user_id, kinds)
        return [
            UserMemory(
                memory_id=row["memory_id"], tenant_id=row["tenant_id"],
                user_id=row["user_id"], kind=row["kind"], key=row["key"],
                value=row["value"], confidence=row["confidence"],
                source_task_id=row["source_task_id"],
                updated_at=_as_datetime(row["updated_at"]),
                expires_at=(
                    _as_datetime(row["expires_at"])
                    if row["expires_at"] else None
                ),
            )
            for row in rows
        ]

    async def append_message(self, session_id: str, task_id: str | None,
                             role: str, content: str) -> None:
        await self.messages.append(session_id, task_id, role, content)

    async def recent_messages(self, session_id: str,
                              limit: int = 10) -> list[dict]:
        return await self.messages.recent(session_id, limit)

    async def list_messages(self, session_id: str,
                            limit: int = 100) -> list[dict]:
        return await self.messages.list(session_id, limit)
