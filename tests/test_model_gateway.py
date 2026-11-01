from types import SimpleNamespace

import fakeredis.aioredis
import pytest

from itinerary_agent.domain.models import CallContext, ModelTier
from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.repositories import PostgresModelCallRepository
from itinerary_agent.infra.repositories.llm_cache_repository import (
    PostgresLLMCache,
)
from itinerary_agent.model_gateway.circuit import RedisCircuitBreaker
from itinerary_agent.model_gateway.errors import (
    ModelBudgetExceeded,
    ModelUnavailable,
)
from itinerary_agent.model_gateway.gateway import OpenAIChatGateway
from itinerary_agent.model_gateway.router import resolve_model
from tests.db_utils import open_test_db


class FakeStream:
    """最小异步流；可在若干 chunk 后抛错。"""

    def __init__(self, chunks: list[str], error: Exception | None = None):
        self.chunks = chunks
        self.error = error

    async def __aiter__(self):
        for text in self.chunks:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=text))],
                usage=None,
            )
        if self.error is not None:
            raise self.error
        yield SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )


class FakeClient:
    """最小 OpenAI 兼容客户端：按顺序返回响应或抛异常。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
        self.chat = self
        self.completions = self

    async def create(self, **kwargs):
        self.calls += 1
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _response(text: str, prompt: int = 100, completion: int = 50):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(
            prompt_tokens=prompt, completion_tokens=completion
        ),
    )


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "model_light": "deepseek-chat",
        "model_standard": "deepseek-chat",
        "model_reasoning": "deepseek-chat",
        "fallback_model_light": "qwen-plus",
        "fallback_model_standard": "qwen-plus",
        "fallback_model_reasoning": "qwen-plus",
        "model_pricing_file": "config/pricing.yaml",
    }
    values.update(overrides)
    return Settings(**values)


def _ctx(purpose: str = "plan") -> CallContext:
    return CallContext(
        trace_id="trace-1", tenant_id="demo-company",
        task_id="task-1", purpose=purpose,
    )


def test_tier_routing():
    # 档位到具体模型的映射只由配置决定，业务代码不写死厂商模型 ID。
    settings = _settings(
        model_light="light-m",
        model_standard="std-m",
        model_reasoning="reason-m",
    )
    assert resolve_model(settings, "light") == "light-m"
    assert resolve_model(settings, "reasoning") == "reason-m"


async def test_fallback_on_primary_failure():
    primary = FakeClient([RuntimeError("upstream down")])
    fallback = FakeClient([_response('{"steps":["search_hotels"]}')])
    gateway = OpenAIChatGateway(
        _settings(), primary_client=primary, fallback_client=fallback
    )

    result = await gateway.complete(
        _ctx(), [{"role": "user", "content": "plan"}], ModelTier.STANDARD
    )

    assert primary.calls == 1
    assert fallback.calls == 1
    assert result.provider == "dashscope"
    assert result.model == "qwen-plus"
    assert result.fallback_from == "deepseek-chat"
    assert result.cost_usd > 0


async def test_schema_repair_retries_once():
    primary = FakeClient([_response("not json"), _response('{"value": 1}')])
    gateway = OpenAIChatGateway(
        _settings(model_fallback_enabled=False), primary_client=primary
    )
    schema = {
        "type": "object",
        "required": ["value"],
        "properties": {"value": {"type": "integer"}},
    }

    result = await gateway.complete(
        _ctx(), [{"role": "user", "content": "x"}],
        ModelTier.LIGHT, response_schema=schema,
    )

    assert primary.calls == 2
    assert '"value": 1' in result.text


async def test_all_providers_fail_raises_unavailable():
    primary = FakeClient([RuntimeError("primary")])
    fallback = FakeClient([RuntimeError("fallback")])
    gateway = OpenAIChatGateway(
        _settings(), primary_client=primary, fallback_client=fallback
    )

    with pytest.raises(ModelUnavailable):
        await gateway.complete(
            _ctx(), [{"role": "user", "content": "x"}], ModelTier.LIGHT
        )


async def test_cache_hit_and_ledger(tmp_path):
    db = await open_test_db()
    primary = FakeClient([
        _response('{"destination_city":"北京"}'),
    ])
    gateway = OpenAIChatGateway(
        _settings(model_fallback_enabled=False),
        ledger=PostgresModelCallRepository(db),
        cache=PostgresLLMCache(db),
        primary_client=primary,
    )
    ctx = _ctx(purpose="understand")
    messages = [{"role": "user", "content": "去北京"}]
    schema = {"type": "object", "properties": {}}

    first = await gateway.complete(
        ctx, messages, ModelTier.LIGHT, response_schema=schema
    )
    second = await gateway.complete(
        ctx, messages, ModelTier.LIGHT, response_schema=schema
    )

    assert primary.calls == 1
    assert first.cost_usd > 0
    assert second.cost_usd == 0
    rows = await db.fetchall(
        "SELECT cache_hit, cost_usd FROM llm_calls ORDER BY created_at"
    )
    assert [row["cache_hit"] for row in rows] == [False, True]
    await db.close()


async def test_stream_falls_back_before_first_token():
    primary = FakeClient([RuntimeError("primary down")])
    fallback = FakeClient([FakeStream(["你", "好"])])
    gateway = OpenAIChatGateway(
        _settings(), primary_client=primary, fallback_client=fallback
    )

    chunks = [
        chunk async for chunk in gateway.stream(
            _ctx(purpose="summarize"),
            [{"role": "user", "content": "总结"}],
            ModelTier.STANDARD,
        )
    ]

    assert chunks == ["你", "好"]
    assert primary.calls == 1
    assert fallback.calls == 1


async def test_stream_does_not_fall_back_after_first_token():
    primary = FakeClient([
        FakeStream(["半"], error=RuntimeError("stream broken"))
    ])
    fallback = FakeClient([FakeStream(["坏"])])
    gateway = OpenAIChatGateway(
        _settings(), primary_client=primary, fallback_client=fallback
    )

    chunks = []
    with pytest.raises(ModelUnavailable):
        async for chunk in gateway.stream(
            _ctx(purpose="summarize"),
            [{"role": "user", "content": "总结"}],
            ModelTier.STANDARD,
        ):
            chunks.append(chunk)

    assert chunks == ["半"]
    assert fallback.calls == 0


async def test_circuit_breaker_skips_open_primary():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    breaker = RedisCircuitBreaker(
        redis, "test", failure_threshold=1,
        cooldown_seconds=60, clock=lambda: 1000.0,
    )
    primary = FakeClient([RuntimeError("down")])
    fallback = FakeClient([_response("fallback answer")])
    gateway = OpenAIChatGateway(
        _settings(), primary_client=primary, fallback_client=fallback,
        breaker=breaker,
    )
    messages = [{"role": "user", "content": "x"}]

    first = await gateway.complete(
        _ctx(), messages, ModelTier.STANDARD
    )
    assert first.provider == "dashscope"

    # 主提供方已熔断：第二次不再调用 primary，直接走 fallback。
    next_primary = FakeClient([_response("should not be used")])
    next_fallback = FakeClient([_response("fallback again")])
    gateway.client = next_primary
    gateway.fallback_client = next_fallback
    second = await gateway.complete(_ctx(), messages, ModelTier.STANDARD)

    assert next_primary.calls == 0
    assert next_fallback.calls == 1
    assert second.provider == "dashscope"
    await redis.aclose()


async def test_ledger_records_prompt_version():
    db = await open_test_db()
    primary = FakeClient([_response('{"destination_city":"北京"}')])
    gateway = OpenAIChatGateway(
        _settings(model_fallback_enabled=False),
        ledger=PostgresModelCallRepository(db),
        primary_client=primary,
    )
    ctx = CallContext(
        trace_id="trace-1", tenant_id="demo-company", task_id="task-1",
        purpose="understand", prompt_version="v2",
    )

    await gateway.complete(
        ctx, [{"role": "user", "content": "去北京"}], ModelTier.LIGHT
    )

    row = await db.fetchone(
        "SELECT prompt_version FROM llm_calls ORDER BY created_at DESC LIMIT 1"
    )
    assert row["prompt_version"] == "v2"
    await db.close()


async def test_task_budget_blocks_model_call():
    class UsageLedger:
        async def task_usage(self, task_id: str) -> dict:
            return {"tokens": 100, "cost_usd": 0.1}

    primary = FakeClient([_response("should not be called")])
    gateway = OpenAIChatGateway(
        _settings(
            model_fallback_enabled=False, task_token_budget=50,
        ),
        ledger=UsageLedger(), primary_client=primary,
    )

    with pytest.raises(ModelBudgetExceeded):
        await gateway.complete(
            _ctx(), [{"role": "user", "content": "x"}], ModelTier.LIGHT
        )
    assert primary.calls == 0
