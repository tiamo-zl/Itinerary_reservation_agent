"""Redis 固定窗口限流。

聊天/反馈等读路径在 Redis 故障时 fail-open；
管理员审批决定 fail-closed，避免限流失效时被滥用。
"""

import logging
import time
from dataclasses import dataclass

from itinerary_agent.infra.config import Settings

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60


@dataclass
class RateLimitDecision:
    allowed: bool
    limit: int = 0
    remaining: int = 0
    retry_after: int = 0
    degraded: bool = False


class RateLimiter:
    def __init__(self, redis_client, settings: Settings):
        self.redis = redis_client
        self.settings = settings
        self.enabled = settings.rate_limit_enabled
        self.limits = {
            "chat": settings.rate_limit_chat_per_minute,
            "approval": settings.rate_limit_approval_per_minute,
            "feedback": settings.rate_limit_feedback_per_minute,
        }
        self.prefix = f"{settings.environment}:ratelimit:"

    async def check(self, scope: str, identity: str) -> RateLimitDecision:
        limit = self.limits.get(scope, 0)
        if not self.enabled or limit <= 0 or self.redis is None:
            return RateLimitDecision(allowed=True, limit=limit)

        now = int(time.time())
        window = now // WINDOW_SECONDS
        key = f"{self.prefix}{scope}:{identity}:{window}"
        try:
            current = await self._increment(key)
        except Exception:
            logger.exception("rate limiter unavailable scope=%s", scope)
            fail_open = scope != "approval"
            return RateLimitDecision(
                allowed=fail_open, limit=limit, degraded=True
            )

        if current > limit:
            return RateLimitDecision(
                allowed=False,
                limit=limit,
                remaining=0,
                retry_after=WINDOW_SECONDS - (now % WINDOW_SECONDS),
            )
        return RateLimitDecision(
            allowed=True, limit=limit, remaining=max(limit - current, 0)
        )

    async def _increment(self, key: str) -> int:
        pipe = self.redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, WINDOW_SECONDS + 5)
        result = await pipe.execute()
        return int(result[0])
