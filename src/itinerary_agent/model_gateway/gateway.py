"""OpenAI 兼容聊天网关。

所有业务节点只调用这里，不直接碰 OpenAI/DeepSeek SDK。
网关负责分档路由、缓存、成本记录、超时与 SDK 自带重试。
"""

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from openai import AsyncOpenAI

from itinerary_agent.domain.models import CallContext, Completion, ModelTier
from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.db import Database
from itinerary_agent.model_gateway.router import resolve_model


class OpenAIChatGateway:
    def __init__(self, settings: Settings, db: Database | None = None):
        self.settings = settings
        self.db = db
        self.client = AsyncOpenAI(
            base_url=settings.deepseek_base_url,
            api_key=settings.deepseek_api_key or "missing",
            timeout=30,
            max_retries=2,
        )

    async def complete(self, ctx: CallContext, messages: list[dict],
                       tier: ModelTier, response_schema: dict | None = None) -> Completion:
        model = resolve_model(self.settings, tier.value)
        messages = list(messages)
        if response_schema:
            messages.append({
                "role": "user",
                "content": "只输出 JSON，并满足给定 schema。",
            })

        kwargs = {"model": model, "messages": messages, "temperature": 0}
        if response_schema:
            kwargs["response_format"] = {"type": "json_object"}

        # 只缓存确定性高的用途；规划类请求随上下文变化，缓存收益低且易失效。
        cacheable = ctx.purpose in {"classify", "understand"}
        cache_key = hashlib.sha256(
            json.dumps(
                [model, messages, response_schema],
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        if cacheable and self.db is not None:
            row = await self.db.fetchone(
                "SELECT value FROM llm_cache WHERE cache_key = ?", (cache_key,)
            )
            if row:
                return Completion.model_validate_json(row["value"])

        resp = await self.client.chat.completions.create(**kwargs)
        usage = resp.usage
        result = Completion(
            text=resp.choices[0].message.content or "",
            model=model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )

        if self.db is not None:
            if cacheable:
                await self.db.execute(
                    "INSERT OR REPLACE INTO llm_cache (cache_key, value, created_at) "
                    "VALUES (?, ?, ?)",
                    (cache_key, result.model_dump_json(), datetime.now(UTC).isoformat()),
                )
            # cost_usd 暂时记 0，后续接入价格表后按模型/租户补全。
            await self.db.execute(
                "INSERT INTO llm_calls (call_id, trace_id, task_id, tenant_id, purpose, "
                "model, prompt_tokens, completion_tokens, cost_usd, duration_ms, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    uuid4().hex, ctx.trace_id, ctx.task_id, ctx.tenant_id, ctx.purpose,
                    model, result.prompt_tokens, result.completion_tokens,
                    result.cost_usd, 0.0, datetime.now(UTC).isoformat(),
                ),
            )
        return result

    async def stream(self, ctx: CallContext, messages: list[dict], tier: ModelTier):
        # M3 先做伪流式，保证接口稳定；真正的 token 流在 M5 可替换实现。
        completion = await self.complete(ctx, messages, tier)
        yield completion.text

    async def embed(self, ctx: CallContext, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("use DashScopeEmbedder")
