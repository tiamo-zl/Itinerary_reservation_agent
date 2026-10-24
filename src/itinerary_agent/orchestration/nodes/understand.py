"""需求理解节点：自然语言 → TripRequest。"""

import json
import re
from datetime import date, timedelta

from itinerary_agent.domain.models import (
    CallContext,
    HumanRequest,
    HumanRequestType,
    TripRequest,
)

# 明确列出目标字段，避免真实模型输出 destination/departure_date 等别名。
SYSTEM_TEMPLATE = """你是差旅需求解析器。今天是 {today}。
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

WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5,
            "日": 6, "天": 6}

ALIASES = {
    "destination": "destination_city",
    "departure_date": "start_date",
    "return_date": "end_date",
    "budget": "budget_limit",
    "duration_days": "duration_days",
}


def _load_json(text: str) -> dict:
    """容忍模型偶尔输出的 ```json 代码块。"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("model output is not a JSON object")
    return json.loads(text[start:end + 1])


def _parse_relative_date(value, today: date):
    """把“下周二/明天/3天后”等常见表达转成 ISO 日期。"""
    if not isinstance(value, str):
        return value
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    if value in {"今天", "今日"}:
        return today.isoformat()
    if value == "明天":
        return (today + timedelta(days=1)).isoformat()
    if value == "后天":
        return (today + timedelta(days=2)).isoformat()

    match = re.fullmatch(r"(下|本|这)?周([一二三四五六日天])", value)
    if match:
        prefix, weekday_text = match.groups()
        target = WEEKDAYS[weekday_text]
        monday = today - timedelta(days=today.weekday())
        if prefix == "下":
            base = monday + timedelta(days=7)
        elif prefix in {"本", "这"}:
            base = monday
        else:
            delta = (target - today.weekday()) % 7
            return (today + timedelta(days=delta)).isoformat()
        return (base + timedelta(days=target)).isoformat()

    match = re.fullmatch(r"(\d+)天后", value)
    if match:
        return (today + timedelta(days=int(match.group(1)))).isoformat()
    return value


def normalize_payload(raw: dict, today: date | None = None) -> dict:
    """把模型常见别名/相对日期归一化为 TripRequest 字段。"""
    today = today or date.today()
    data: dict = {}
    for key, value in raw.items():
        data[ALIASES.get(key, key)] = value

    duration = data.pop("duration_days", None)
    if "start_date" in data:
        data["start_date"] = _parse_relative_date(data["start_date"], today)
    if "end_date" in data:
        data["end_date"] = _parse_relative_date(data["end_date"], today)

    # “出差两天”通常对应 start_date + 1 天结束。
    if not data.get("end_date") and data.get("start_date"):
        try:
            start = date.fromisoformat(data["start_date"])
            days = int(duration) if duration else 1
            data["end_date"] = (start + timedelta(days=max(days - 1, 0))).isoformat()
        except (ValueError, TypeError):
            pass

    data.setdefault("need_flight", True)
    data.setdefault("need_hotel", True)
    return data


async def understand(state: dict, deps) -> dict:
    ctx = CallContext(
        trace_id=state["trace_id"], tenant_id=state["tenant_id"],
        task_id=state["task_id"], purpose="understand",
    )
    system = SYSTEM_TEMPLATE.format(today=date.today().isoformat())
    async with deps.span("orchestration.node.understand", "orchestration"):
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": state["request"].get("raw_message", "")},
        ]
        completion = await deps.model.complete(
            ctx, messages, deps.tier_light,
            response_schema=TripRequest.model_json_schema(),
        )

    try:
        raw = normalize_payload(_load_json(completion.text))
        request = TripRequest.model_validate(raw)
    except Exception:  # noqa: BLE001 - 模型输出不可信，解析失败转为追问
        # 解析失败时不要带着空槽位继续规划，交给网关转成追问。
        human = HumanRequest(
            type=HumanRequestType.CLARIFY,
            message="没能理解差旅需求，请补充目的地、出行日期和预算。",
        )
        return {"status": "WAITING_HUMAN",
                "pending_human": human.model_dump(mode="json")}

    if not request.destination_city:
        human = HumanRequest(type=HumanRequestType.CLARIFY, message="请提供目的地。")
        return {"status": "WAITING_HUMAN",
                "pending_human": human.model_dump(mode="json")}
    return {"request": request.model_dump(mode="json"), "status": "EXECUTING"}
