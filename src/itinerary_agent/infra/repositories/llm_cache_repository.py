"""PostgreSQL 版 LLM 缓存，作为 Redis 不可用时的兼容实现。"""

import logging
from datetime import UTC, datetime, timedelta

from itinerary_agent.infra.db import Database

logger = logging.getLogger(__name__)


class PostgresLLMCache:
    def __init__(self, db: Database, ttl_seconds: int = 86400):
        self.db = db
        self.ttl_seconds = ttl_seconds

    async def get(self, key: str) -> str | None:
        try:
            row = await self.db.fetchone(
                "SELECT value FROM llm_cache WHERE cache_key = ? "
                "AND (expires_at IS NULL OR expires_at > now())",
                (key,),
            )
            return row["value"] if row else None
        except Exception:
            logger.exception("postgres llm cache read failed")
            return None

    async def set(self, key: str, value: str) -> None:
        expires_at = datetime.now(UTC) + timedelta(seconds=self.ttl_seconds)
        try:
            await self.db.execute(
                "INSERT INTO llm_cache (cache_key, value, created_at, expires_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT (cache_key) DO UPDATE SET "
                "value=EXCLUDED.value, created_at=EXCLUDED.created_at, "
                "expires_at=EXCLUDED.expires_at",
                (
                    key, value, datetime.now(UTC),
                    expires_at,
                ),
            )
        except Exception:
            logger.exception("postgres llm cache write failed")
