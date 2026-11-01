"""Redis 限流与缓存。"""

from types import SimpleNamespace

import fakeredis.aioredis
from fastapi.testclient import TestClient

from itinerary_agent.api.app import create_app
from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.container import build_container
from itinerary_agent.infra.rate_limit import RateLimiter
from itinerary_agent.model_gateway.cache import RedisLLMCache
from tests.db_utils import make_test_settings


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "environment": "test",
        "rate_limit_chat_per_minute": 2,
        "rate_limit_approval_per_minute": 1,
        "rate_limit_feedback_per_minute": 1,
    }
    values.update(overrides)
    return Settings(**values)


async def test_fixed_window_rate_limit():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    limiter = RateLimiter(redis, _settings())

    first = await limiter.check("chat", "demo-company:u001")
    second = await limiter.check("chat", "demo-company:u001")
    third = await limiter.check("chat", "demo-company:u001")

    assert first.allowed and second.allowed
    assert first.remaining == 1
    assert third.allowed is False
    assert third.retry_after > 0
    await redis.aclose()


async def test_redis_failure_is_fail_open_for_chat_and_closed_for_approval():
    class BrokenRedis:
        def pipeline(self):
            raise RuntimeError("redis down")

    limiter = RateLimiter(BrokenRedis(), _settings())
    chat = await limiter.check("chat", "demo-company:u001")
    approval = await limiter.check("approval", "demo-company:u002")

    assert chat.allowed and chat.degraded
    assert approval.allowed is False and approval.degraded


def test_rate_limited_request_returns_429(tmp_path):
    class DenyLimiter:
        async def check(self, scope, identity):
            return SimpleNamespace(
                allowed=False, limit=1, remaining=0,
                retry_after=42, degraded=False,
            )

    container = build_container(make_test_settings())
    container.rate_limiter = DenyLimiter()
    app = create_app(container)

    with TestClient(app) as client:
        response = client.post("/chat", json={"message": "去北京"})

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "42"


async def test_redis_cache_roundtrip_with_ttl():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cache = RedisLLMCache(redis, ttl_seconds=60, prefix="test:llm:")

    await cache.set("key", "value")
    assert await cache.get("key") == "value"
    assert await redis.ttl("test:llm:key") > 0
    await redis.aclose()
