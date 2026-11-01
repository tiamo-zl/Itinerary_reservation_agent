"""OpenAI 兼容聊天网关。

所有业务节点只调用这里，不直接碰 OpenAI/DeepSeek SDK。
网关负责分档路由、缓存、主备切换、结构化校验、成本记录与超时。
"""

import asyncio
import hashlib
import json
import logging
from time import perf_counter

from openai import AsyncOpenAI

from itinerary_agent.domain.models import CallContext, Completion, ModelTier
from itinerary_agent.infra.config import Settings
from itinerary_agent.model_gateway.cache import LLMCache
from itinerary_agent.model_gateway.errors import ModelOutputError, ModelUnavailable
from itinerary_agent.model_gateway.json_output import parse_and_validate
from itinerary_agent.model_gateway.pricing import PriceTable
from itinerary_agent.model_gateway.router import (
    resolve_fallback_model,
    resolve_model,
)
from itinerary_agent.observability.metrics import (
    LLM_CACHE_HITS,
    LLM_CACHE_MISSES,
    MODEL_CALLS,
    MODEL_COST,
    MODEL_ERRORS,
    MODEL_TOKENS,
)

logger = logging.getLogger(__name__)

JSON_INSTRUCTION = "只输出 JSON，并满足给定 schema。"
REPAIR_INSTRUCTION = (
    "上一次输出不是合法 JSON 或不符合 schema：{error}。"
    "只输出修正后的 JSON 对象，不要解释。"
)


class _NullSpan:
    """没有 TraceRecorder 时的空 span。"""

    async def __aenter__(self):
        return None

    async def __aexit__(self, *args):
        return False


class OpenAIChatGateway:
    def __init__(self, settings: Settings, ledger=None, traces=None,
                 primary_client=None, fallback_client=None,
                 cache: LLMCache | None = None):
        self.settings = settings
        self.ledger = ledger
        self.traces = traces
        self.client = primary_client or AsyncOpenAI(
            base_url=settings.deepseek_base_url,
            api_key=settings.deepseek_api_key or "missing",
            timeout=settings.model_timeout_seconds,
            max_retries=settings.model_max_retries,
        )
        fallback_key = settings.fallback_api_key or settings.dashscope_api_key
        if fallback_client is not None:
            self.fallback_client = fallback_client
        elif settings.model_fallback_enabled and fallback_key:
            self.fallback_client = AsyncOpenAI(
                base_url=settings.fallback_base_url,
                api_key=fallback_key,
                timeout=settings.model_timeout_seconds,
                max_retries=settings.model_max_retries,
            )
        else:
            self.fallback_client = None
        self.pricing = PriceTable.load(settings.model_pricing_file)
        # 缓存实现由容器注入：生产 Redis，单测/无 Redis 时可注入 Postgres。
        self.cache = cache

    def _candidates(self, tier: ModelTier) -> list[tuple[str, object, str]]:
        """主提供方优先，备用提供方只在配置了 key 时加入。"""
        candidates = [(
            self.settings.primary_provider_name,
            self.client,
            resolve_model(self.settings, tier.value),
        )]
        if self.fallback_client is not None:
            candidates.append((
                self.settings.fallback_provider_name,
                self.fallback_client,
                resolve_fallback_model(self.settings, tier.value),
            ))
        return candidates

    async def complete(self, ctx: CallContext, messages: list[dict],
                       tier: ModelTier, response_schema: dict | None = None) -> Completion:
        """执行一次聊天补全。

        步骤：
        1. 按 tier 解析主/备模型；
        2. 需要 JSON 时追加格式约束；
        3. 查询带 TTL 的确定性缓存；
        4. 依次调用主提供方和备用提供方；
        5. 结构化输出校验，失败做一次修复重试；
        6. 写缓存和 token/成本账本，返回统一 Completion。
        """
        messages = list(messages)
        if response_schema:
            messages.append({"role": "user", "content": JSON_INSTRUCTION})

        # 步骤 3：只缓存确定性高的用途。
        cacheable = ctx.purpose in {"classify", "understand"}
        cache_key = self._cache_key(ctx, tier, messages, response_schema)
        if cacheable and self.cache is not None:
            cached = await self.cache.get(cache_key)
            if cached:
                LLM_CACHE_HITS.inc()
                # 命中缓存不产生新的模型费用；token 数保留便于统计。
                completion = Completion.model_validate_json(cached).model_copy(
                    update={"cost_usd": 0.0}
                )
                await self._record(
                    ctx, completion.provider or self.settings.primary_provider_name,
                    completion.model, completion.prompt_tokens,
                    completion.completion_tokens, 0.0, 0.0,
                    status="ok", cache_hit=True, attempt=0,
                )
                return completion
            LLM_CACHE_MISSES.inc()

        # 步骤 4/5：主备切换；每个候选内部最多一次修复。
        last_error: Exception | None = None
        fallback_from: str | None = None
        for attempt, (provider, client, model) in enumerate(
            self._candidates(tier), start=1
        ):
            started = perf_counter()
            span = (
                self.traces.span(
                    f"model.{ctx.purpose}", "model",
                    provider=provider, model=model,
                    prompt_version=ctx.prompt_version,
                    fallback_from=fallback_from,
                )
                if self.traces is not None else _NullSpan()
            )
            try:
                async with span:
                    completion = await self._call(
                        client, model, messages, response_schema
                    )
                    if response_schema:
                        completion = await self._validate_or_repair(
                            client, model, messages, completion, response_schema
                        )
            except Exception as exc:  # noqa: BLE001 - 主备切换需要捕获上游所有失败
                duration_ms = (perf_counter() - started) * 1000
                error_code = self._error_code(exc)
                await self._record(
                    ctx, provider, model, 0, 0, 0.0, duration_ms,
                    status="error", error_code=error_code,
                    fallback_from=fallback_from, attempt=attempt,
                )
                logger.warning(
                    "model call failed provider=%s model=%s code=%s: %s",
                    provider, model, error_code, exc,
                )
                MODEL_CALLS.labels(
                    provider=provider, status="error",
                    fallback=str(bool(fallback_from)),
                ).inc()
                MODEL_ERRORS.labels(
                    provider=provider, code=error_code
                ).inc()
                last_error = exc
                if provider == self.settings.primary_provider_name:
                    fallback_from = model
                continue

            duration_ms = (perf_counter() - started) * 1000
            cost = self.pricing.cost(
                provider, model, completion.prompt_tokens,
                completion.completion_tokens,
            )
            result = completion.model_copy(update={
                "cost_usd": cost,
                "provider": provider,
                "fallback_from": fallback_from,
            })
            MODEL_CALLS.labels(
                provider=provider, status="ok",
                fallback=str(bool(fallback_from)),
            ).inc()
            MODEL_TOKENS.labels(provider=provider, kind="prompt").inc(
                result.prompt_tokens
            )
            MODEL_TOKENS.labels(
                provider=provider, kind="completion"
            ).inc(result.completion_tokens)
            MODEL_COST.labels(provider=provider).inc(cost)
            await self._record(
                ctx, provider, model, result.prompt_tokens,
                result.completion_tokens, cost, duration_ms,
                status="ok", fallback_from=fallback_from, attempt=attempt,
            )
            if cacheable and self.cache is not None:
                await self.cache.set(cache_key, result.model_dump_json())
            return result

        raise ModelUnavailable("所有模型提供方均不可用") from last_error

    async def _call(self, client, model: str, messages: list[dict],
                    response_schema: dict | None) -> Completion:
        kwargs = {"model": model, "messages": messages, "temperature": 0}
        if response_schema:
            kwargs["response_format"] = {"type": "json_object"}
        async with asyncio.timeout(self.settings.model_timeout_seconds):
            resp = await client.chat.completions.create(**kwargs)
        usage = resp.usage
        return Completion(
            text=resp.choices[0].message.content or "",
            model=model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )

    async def _validate_or_repair(self, client, model: str,
                                  messages: list[dict], completion: Completion,
                                  schema: dict) -> Completion:
        """校验结构化输出；失败时带错误信息重试一次。"""
        try:
            parse_and_validate(completion.text, schema)
            return completion
        except Exception as exc:  # noqa: BLE001 - 校验失败需要进入修复流程
            repair_messages = [
                *messages,
                {"role": "assistant", "content": completion.text},
                {"role": "user", "content": REPAIR_INSTRUCTION.format(error=exc)},
            ]
            repaired = await self._call(client, model, repair_messages, schema)
            try:
                parse_and_validate(repaired.text, schema)
            except Exception as repair_error:
                raise ModelOutputError(
                    f"model output failed schema validation: {repair_error}"
                ) from repair_error
            return repaired

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if isinstance(exc, ModelOutputError):
            return exc.code
        if isinstance(exc, TimeoutError):
            return "MODEL_TIMEOUT"
        return "MODEL_UPSTREAM"

    def _cache_key(self, ctx: CallContext, tier: ModelTier,
                   messages: list[dict], schema: dict | None) -> str:
        payload = [
            ctx.tenant_id,
            ctx.prompt_version,
            resolve_model(self.settings, tier.value),
            messages,
            schema,
        ]
        return hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, ensure_ascii=False, default=str
            ).encode()
        ).hexdigest()

    async def _record(self, ctx: CallContext, provider: str, model: str,
                      prompt_tokens: int, completion_tokens: int, cost: float,
                      duration_ms: float, status: str,
                      error_code: str | None = None,
                      cache_hit: bool = False,
                      fallback_from: str | None = None,
                      attempt: int = 1) -> None:
        """写调用账本；观测失败不能反向破坏业务。"""
        if self.ledger is None:
            return
        try:
            await self.ledger.record(
                trace_id=ctx.trace_id,
                task_id=ctx.task_id,
                tenant_id=ctx.tenant_id,
                purpose=ctx.purpose,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost,
                duration_ms=duration_ms,
                provider=provider,
                prompt_version=ctx.prompt_version,
                status=status,
                error_code=error_code,
                cache_hit=cache_hit,
                fallback_from=fallback_from,
                attempt=attempt,
            )
        except Exception:
            logger.exception("llm call ledger write failed")

    async def stream(self, ctx: CallContext, messages: list[dict], tier: ModelTier):
        # 真流式放到 P1；这里保持接口稳定。
        completion = await self.complete(ctx, messages, tier)
        yield completion.text

    async def embed(self, ctx: CallContext, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("use DashScopeEmbedder")
