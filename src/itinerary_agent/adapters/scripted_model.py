"""脚本化模型网关。

用于 M1 在没有 API Key 的情况下跑通编排主链路：
按顺序返回预先写好的响应，模拟模型输出。
"""

from collections import deque

from itinerary_agent.domain.models import CallContext, Completion, ModelTier


class ScriptedModelGateway:
    def __init__(self, responses: list[str]):
        self._responses = deque(responses)

    async def complete(self, ctx: CallContext, messages: list[dict],
                       tier: ModelTier, response_schema: dict | None = None) -> Completion:
        # 响应耗尽时返回空对象，避免测试因意外多调用而崩溃。
        text = self._responses.popleft() if self._responses else "{}"
        return Completion(text=text, model="scripted")

    async def stream(self, ctx: CallContext, messages: list[dict],
                     tier: ModelTier):
        completion = await self.complete(ctx, messages, tier)
        yield completion.text

    async def embed(self, ctx: CallContext, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 1024 for _ in texts]
