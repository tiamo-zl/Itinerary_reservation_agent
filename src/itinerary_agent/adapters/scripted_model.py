"""脚本化模型网关。

用于 M1 在没有 API Key 的情况下跑通编排主链路：
按顺序返回预先写好的响应，模拟模型输出。
"""

import json
import re
from collections import deque

from itinerary_agent.domain.models import CallContext, Completion, ModelTier

_CITIES = ("北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京")
_CN_NUM = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


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


def _parse_demo_request(text: str) -> dict:
    """解析 demo 常见中文需求，供无 Key/无 Milvus 的离线演示使用。"""
    data: dict = {
        "destination_city": next((c for c in _CITIES if c in text), None),
        # demo 用户默认从上海出发；真实模型由用户画像/请求解析。
        "origin_city": "上海",
        "start_date": None,
        "end_date": None,
        "budget_limit": None,
        "hotel_area": None,
        "cabin": "economy",
        "need_flight": True,
        "need_hotel": True,
        "purpose": "出差",
    }

    for pattern in (
        r"\d{4}-\d{2}-\d{2}",
        r"(?:下|本|这)?周[一二三四五六日天]",
        r"今天|明天|后天",
        r"\d+天后",
    ):
        match = re.search(pattern, text)
        if match:
            data["start_date"] = match.group(0)
            break

    duration = re.search(r"([一二两三四五六七八九十\d]+)\s*天", text)
    if duration:
        raw = duration.group(1)
        days = int(raw) if raw.isdigit() else _CN_NUM.get(raw, 1)
        data["duration_days"] = days

    budget = re.search(r"(\d+)\s*(?:元|块)", text)
    if budget:
        data["budget_limit"] = int(budget.group(1))

    area = re.search(r"住(?:在)?\s*([^，,。\s]+?)(?:附近|周边|，|,|。|$)", text)
    if area:
        candidate = area.group(1)
        if candidate not in {"酒店", "宾馆", "饭店"}:
            data["hotel_area"] = candidate

    if any(word in text for word in ("只住酒店", "只订酒店", "不用机票", "不需要机票")):
        data["need_flight"] = False
    if any(word in text for word in ("只订机票", "不用酒店", "不需要酒店", "当日往返")):
        data["need_hotel"] = False
    if "商务舱" in text:
        data["cabin"] = "business"
    elif "头等舱" in text:
        data["cabin"] = "first"
    return data


class DemoScriptedModelGateway(ScriptedModelGateway):
    """离线演示模型：按 prompt 用途返回确定性的结构化结果。

    不是通用 NLU；只覆盖 readme/演示里出现的中文差旅表达。
    """

    async def complete(self, ctx: CallContext, messages: list[dict],
                       tier: ModelTier, response_schema: dict | None = None) -> Completion:
        purpose = getattr(ctx, "purpose", "")
        user_text = str(messages[-1].get("content", "")) if messages else ""
        if purpose == "understand":
            text = json.dumps(_parse_demo_request(user_text), ensure_ascii=False)
        elif purpose == "plan":
            text = '{"steps":["search_flights","search_hotels"]}'
        elif purpose == "summarize":
            text = "差旅方案已处理完成。"
        elif purpose == "judge":
            text = '{"score":5,"verdict":"pass","reason":"scripted demo"}'
        else:
            text = "{}"
        return Completion(text=text, model="demo-scripted")

    async def stream(self, ctx: CallContext, messages: list[dict],
                     tier: ModelTier):
        completion = await self.complete(ctx, messages, tier)
        yield completion.text
