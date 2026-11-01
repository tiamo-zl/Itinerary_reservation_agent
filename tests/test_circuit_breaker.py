"""Redis 共享熔断状态机。"""

import fakeredis.aioredis

from itinerary_agent.model_gateway.circuit import RedisCircuitBreaker


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds: float):
        self.now += seconds


def _breaker(redis, clock, threshold: int = 2) -> RedisCircuitBreaker:
    return RedisCircuitBreaker(
        redis, "test", failure_threshold=threshold,
        cooldown_seconds=10, trial_seconds=5, clock=clock,
    )


async def test_open_half_open_and_close():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    clock = FakeClock()
    breaker = _breaker(redis, clock)

    assert await breaker.allow("deepseek") is True
    await breaker.failure("deepseek")
    assert await breaker.allow("deepseek") is True
    await breaker.failure("deepseek")  # 达到阈值，打开

    assert await breaker.allow("deepseek") is False

    clock.advance(11)
    assert await breaker.allow("deepseek") is True  # 半开，占用试探名额
    assert await breaker.allow("deepseek") is False  # 同一时间只允许一个试探

    await breaker.success("deepseek")
    assert await breaker.allow("deepseek") is True
    await redis.aclose()


async def test_half_open_failure_reopens():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    clock = FakeClock()
    breaker = _breaker(redis, clock, threshold=1)

    await breaker.failure("deepseek")
    assert await breaker.allow("deepseek") is False
    clock.advance(11)
    assert await breaker.allow("deepseek") is True
    await breaker.failure("deepseek")
    assert await breaker.allow("deepseek") is False
    await redis.aclose()


async def test_redis_failure_fails_open():
    class BrokenRedis:
        async def get(self, key):
            raise RuntimeError("redis down")

    breaker = _breaker(BrokenRedis(), FakeClock())
    assert await breaker.allow("deepseek") is True
