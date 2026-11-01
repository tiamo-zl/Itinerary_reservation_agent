"""LLM 缓存实现。

默认用 Redis（带 TTL）；Redis 不可用时可以回退到 PostgreSQL。
缓存失败一律降级为未命中，不影响主流程。
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Protocol

logger = logging.getLogger(__name__)


class LLMCache(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str) -> None: ...


class RedisLLMCache:
    def __init__(self, redis_client, ttl_seconds: int = 86400,
                 prefix: str = "llm:"):
        self.redis = redis_client
        self.ttl_seconds = ttl_seconds
        self.prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    async def get(self, key: str) -> str | None:
        try:
            return await self.redis.get(self._key(key))
        except Exception:
            logger.exception("redis llm cache read failed")
            return None

    async def set(self, key: str, value: str) -> None:
        try:
            await self.redis.set(
                self._key(key), value, ex=self.ttl_seconds
            )
        except Exception:
            logger.exception("redis llm cache write failed")


class PostgresLLMCache:
    """兼容实现：Redis 不可用或未配置时使用。"""

    def __init__(self, db, ttl_seconds: int = 86400):
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
                    key, value, datetime.now(UTC).isoformat(),
                    expires_at.isoformat(),
                ),
            )
        except Exception:
            logger.exception("postgres llm cache write failed")
