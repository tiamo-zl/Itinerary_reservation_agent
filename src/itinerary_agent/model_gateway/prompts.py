"""Prompt 注册表。

节点不再内联 prompt 文本；版本号随 CallContext 进入调用账本，
评测集可以按版本对比记录输出。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptTemplate:
    purpose: str
    version: str
    text: str


UNDERSTAND_V1 = """你是差旅需求解析器。今天是 {today}。
只输出一个 JSON 对象，不要 Markdown，不要解释。
必须使用以下字段名：
- destination_city: 目的地城市
- origin_city: 出发城市（未知可为 null）
- start_date: YYYY-MM-DD
- end_date: YYYY-MM-DD
- budget_limit: 数字
- hotel_area: 住宿区域
- cabin: 舱位
- need_flight: 布尔
- need_hotel: 布尔
- purpose: 出差目的
相对日期必须根据今天换算成 YYYY-MM-DD。"""

UNDERSTAND_V2 = """你是差旅需求解析器。今天是 {today}。
只输出一个 JSON 对象，不要 Markdown，不要解释。
必须使用以下字段名，禁止使用 destination、departure_date、budget 等别名：
- destination_city: 目的地城市
- origin_city: 出发城市（未知可为 null）
- start_date: YYYY-MM-DD
- end_date: YYYY-MM-DD
- budget_limit: 数字
- hotel_area: 住宿区域
- cabin: 舱位
- need_flight: 布尔
- need_hotel: 布尔
- purpose: 出差目的
相对日期必须根据今天换算成 YYYY-MM-DD；end_date 必须晚于 start_date。"""

PLAN_V1 = (
    "根据差旅需求生成执行步骤。只输出一个 JSON 对象，格式为 "
    '{"steps":["search_flights","search_hotels"]}，不要 Markdown，不要解释。'
)

SUMMARIZE_V1 = "用一句中文总结本次差旅方案。"

DEFAULT_PROMPTS = {
    "understand": {"v1": UNDERSTAND_V1, "v2": UNDERSTAND_V2},
    "plan": {"v1": PLAN_V1},
    "summarize": {"v1": SUMMARIZE_V1},
}


class PromptRegistry:
    def __init__(self, templates: dict[str, dict[str, str]] | None = None,
                 default_version: str = "v1"):
        self.templates = {
            purpose: dict(versions)
            for purpose, versions in (templates or DEFAULT_PROMPTS).items()
        }
        self.default_version = default_version

    def get(self, purpose: str, version: str | None = None) -> PromptTemplate:
        versions = self.templates.get(purpose)
        if not versions:
            raise KeyError(f"unknown prompt purpose: {purpose}")
        requested = version or self.default_version
        text = versions.get(requested)
        if text is None:
            # 某个 purpose 还没做新版本时回退到 default/latest，避免启动失败。
            fallback = self.default_version
            text = versions.get(fallback)
            if text is None:
                fallback = max(versions)
                text = versions[fallback]
            requested = fallback
        return PromptTemplate(purpose=purpose, version=requested, text=text)

    def versions(self, purpose: str) -> list[str]:
        return sorted(self.templates.get(purpose, {}))


def default_prompt_registry(version: str = "v1") -> PromptRegistry:
    return PromptRegistry(default_version=version)
