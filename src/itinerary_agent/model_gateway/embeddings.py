"""DashScope embedding adapter.

DeepSeek 没有独立的 embedding 接口，制度向量化走阿里云百炼的
OpenAI 兼容接口。批量大小和维度由配置控制。
"""

from openai import AsyncOpenAI

from itinerary_agent.domain.models import CallContext
from itinerary_agent.infra.config import Settings


class DashScopeEmbedder:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = AsyncOpenAI(
            base_url=settings.dashscope_base_url,
            api_key=settings.dashscope_api_key or "missing",
            timeout=60,
            max_retries=2,
        )

    async def embed(self, ctx: CallContext, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.settings.embedding_batch_size):
            batch = texts[start:start + self.settings.embedding_batch_size]
            resp = await self.client.embeddings.create(
                model=self.settings.embedding_model,
                input=batch,
                dimensions=self.settings.embedding_dimensions,
            )
            # DashScope 返回顺序与输入 batch 一致。
            vectors.extend(item.embedding for item in resp.data)
        return vectors
