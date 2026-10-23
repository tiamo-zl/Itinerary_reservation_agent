from itinerary_agent.infra.config import Settings
from itinerary_agent.model_gateway.router import resolve_model


def test_tier_routing():
    # 档位到具体模型的映射只由配置决定，业务代码不写死厂商模型 ID。
    settings = Settings(
        _env_file=None,
        model_light="light-m",
        model_standard="std-m",
        model_reasoning="reason-m",
    )
    assert resolve_model(settings, "light") == "light-m"
    assert resolve_model(settings, "reasoning") == "reason-m"
