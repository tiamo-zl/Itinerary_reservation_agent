"""长期用户偏好仓储。"""

from itinerary_agent.domain.models import UserMemory
from itinerary_agent.infra.db import Database


class PostgresMemoryRepository:
    def __init__(self, db: Database):
        self.db = db

    async def upsert(self, memory: UserMemory) -> None:
        await self.db.execute(
            "INSERT INTO user_memories (memory_id, tenant_id, user_id, kind, key, "
            "value, confidence, source_task_id, updated_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (memory_id) DO UPDATE SET value=EXCLUDED.value, "
            "confidence=EXCLUDED.confidence, updated_at=EXCLUDED.updated_at",
            (
                memory.memory_id, memory.tenant_id, memory.user_id,
                memory.kind, memory.key, memory.value, memory.confidence,
                memory.source_task_id, memory.updated_at,
                memory.expires_at,
            ),
        )

    async def get(self, tenant_id: str, user_id: str,
                  kinds: list[str]) -> list[dict]:
        if not kinds:
            return []
        placeholders = ",".join("?" for _ in kinds)
        rows = await self.db.fetchall(
            f"SELECT * FROM user_memories WHERE tenant_id = ? "
            f"AND user_id = ? AND kind IN ({placeholders})",
            (tenant_id, user_id, *kinds),
        )
        return [dict(row) for row in rows]
