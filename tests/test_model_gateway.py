from types import SimpleNamespace

import pytest

from itinerary_agent.domain.models import CallContext, ModelTier
from itinerary_agent.infra.config import Settings
from itinerary_agent.model_gateway.errors import ModelUnavailable
from itinerary_agent.model_gateway.gateway import OpenAIChatGateway
from itinerary_agent.model_gateway.router import resolve_model
from tests.db_utils import open_test_db


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
        db=db, primary_client=primary,
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
