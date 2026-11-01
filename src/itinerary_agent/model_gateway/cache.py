"""LLM 缓存端口与 Redis 实现。

Redis 不可用时由容器回退到 PostgreSQL（infra/repositories）。
缓存失败一律降级为未命中，不影响主流程。
"""

import logging
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
