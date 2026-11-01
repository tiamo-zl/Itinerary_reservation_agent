"""基于 Redis 的跨进程模型熔断。

状态机：closed → open（连续失败达到阈值）→ half_open（冷却后的一次试探）
→ closed（试探成功）或 open（试探失败）。
Redis 不可用时 fail-open，避免熔断组件本身拖垮业务。
"""

import logging
import time

from itinerary_agent.observability.metrics import (
    CIRCUIT_OPEN,
    CIRCUIT_REDIS_ERRORS,
    CIRCUIT_REJECTED,
    CIRCUIT_TRANSITIONS,
)

logger = logging.getLogger(__name__)


class RedisCircuitBreaker:
    def __init__(self, redis_client, environment: str, *,
                 failure_threshold: int = 5,
                 cooldown_seconds: int = 30,
                 trial_seconds: int = 5,
                 clock=time.time):
        self.redis = redis_client
        self.prefix = f"{environment}:circuit:"
        self.failure_threshold = max(1, failure_threshold)
        self.cooldown_seconds = max(1, cooldown_seconds)
        self.trial_seconds = max(1, trial_seconds)
        self.clock = clock

    def _key(self, provider: str, suffix: str) -> str:
        return f"{self.prefix}{provider}:{suffix}"

    async def allow(self, provider: str) -> bool:
        try:
            state = await self.redis.get(self._key(provider, "state"))
            if state == "open":
                opened_at = await self.redis.get(
                    self._key(provider, "opened_at")
                )
                elapsed = (
                    self.clock() - float(opened_at)
                    if opened_at is not None else 0
                )
                if elapsed < self.cooldown_seconds:
                    CIRCUIT_REJECTED.labels(provider=provider).inc()
                    return False
                await self._transition(provider, "half_open")
                return await self._acquire_trial(provider)
            if state == "half_open":
                return await self._acquire_trial(provider)
            return True
        except Exception:
            logger.exception("circuit breaker read failed provider=%s", provider)
            CIRCUIT_REDIS_ERRORS.inc()
            return True

    async def _acquire_trial(self, provider: str) -> bool:
        acquired = await self.redis.set(
            self._key(provider, "trial"), "1",
            ex=self.trial_seconds, nx=True,
        )
        if not acquired:
            CIRCUIT_REJECTED.labels(provider=provider).inc()
            return False
        return True

    async def success(self, provider: str) -> None:
        try:
            previous = await self.redis.get(self._key(provider, "state"))
            await self.redis.delete(
                self._key(provider, "state"),
                self._key(provider, "failures"),
                self._key(provider, "opened_at"),
                self._key(provider, "trial"),
            )
            CIRCUIT_OPEN.labels(provider=provider).set(0)
            if previous in {"open", "half_open"}:
                self._transition_metric(provider, "closed")
        except Exception:
            logger.exception("circuit breaker success write failed provider=%s",
                             provider)
            CIRCUIT_REDIS_ERRORS.inc()

    async def failure(self, provider: str) -> None:
        try:
            failures = await self.redis.incr(
                self._key(provider, "failures")
            )
            await self.redis.expire(
                self._key(provider, "failures"),
                max(self.cooldown_seconds * 4, 60),
            )
            state = await self.redis.get(self._key(provider, "state"))
            if state == "half_open" or failures >= self.failure_threshold:
                await self.redis.set(
                    self._key(provider, "state"), "open",
                    ex=self.cooldown_seconds * 4,
                )
                await self.redis.set(
                    self._key(provider, "opened_at"), str(self.clock()),
                    ex=self.cooldown_seconds * 4,
                )
                await self.redis.delete(self._key(provider, "trial"))
                CIRCUIT_OPEN.labels(provider=provider).set(1)
                await self._transition(provider, "open")
        except Exception:
            logger.exception("circuit breaker failure write failed provider=%s",
                             provider)
            CIRCUIT_REDIS_ERRORS.inc()

    async def _transition(self, provider: str, to: str) -> None:
        self._transition_metric(provider, to)
        if to == "half_open":
            CIRCUIT_OPEN.labels(provider=provider).set(1)
        elif to == "closed":
            CIRCUIT_OPEN.labels(provider=provider).set(0)

    @staticmethod
    def _transition_metric(provider: str, to: str) -> None:
        CIRCUIT_TRANSITIONS.labels(provider=provider, to=to).inc()
