"""Prompt 注册表版本选择。"""

from itinerary_agent.model_gateway.prompts import default_prompt_registry


def test_prompt_version_selection_and_fallback():
    registry = default_prompt_registry("v2")
    understand = registry.get("understand")
    assert understand.version == "v2"
    assert "禁止使用" in understand.text

    # plan 还没有 v2 时回退到 v1，而不是启动失败。
    plan = registry.get("plan")
    assert plan.version == "v1"
    assert "search_flights" in plan.text

    explicit = registry.get("understand", "v1")
    assert explicit.version == "v1"

    assert registry.versions("understand") == ["v1", "v2"]
