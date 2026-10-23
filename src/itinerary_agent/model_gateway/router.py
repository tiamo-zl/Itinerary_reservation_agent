"""模型档位路由。

业务只表达“要什么能力”（light/standard/reasoning），
具体模型 ID 由部署配置决定，便于切换 DeepSeek/Qwen/Ollama。
"""

from itinerary_agent.infra.config import Settings


def resolve_model(settings: Settings, tier: str) -> str:
    return {
        "light": settings.model_light,
        "standard": settings.model_standard,
        "reasoning": settings.model_reasoning,
    }[tier]
