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

# 真实模型经常输出更自然的英文键名；在进入 Pydantic 校验前先做一次兼容。
# 这样提示词和模型能力有偏差时，不会因为一个字段名就整条链路失败。
ALIASES = {
    "destination": "destination_city",
    "departure_date": "start_date",
    "return_date": "end_date",
    "budget": "budget_limit",
    "duration_days": "duration_days",
}


def _load_json(text: str) -> dict:
    """从模型输出中提取 JSON。

    兼容三类常见偏差：```json 代码块、前后解释文字、JSON 前后空白。
    仍然解析失败时抛异常，由 understand 转成追问，而不是猜测字段。
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("model output is not a JSON object")
    return json.loads(text[start:end + 1])


def _parse_relative_date(value, today: date):
    """把“下周二/明天/3天后”等常见表达转成 ISO 日期。

    步骤：
    1. ISO 日期和今天/明天/后天直接换算；
    2. “下/本/这 + 周X”按周一基准计算；
    3. “N天后”按偏移量计算；
    4. 无法识别时原样返回，由后续校验决定是否追问。
    """
    # 步骤 1：已经是 ISO 或常见短词。
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

    # 步骤 2：“下周X”以“下周一”为基准；“本周X”以“本周一”为基准；
    # 不带前缀的“周X”取今天之后最近的一次。
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

    # 步骤 3：“N天后”按偏移量计算。
    match = re.fullmatch(r"(\d+)天后", value)
    if match:
        return (today + timedelta(days=int(match.group(1)))).isoformat()

    # 步骤 4：无法识别时交给后续校验/追问。
    return value


def normalize_payload(raw: dict, today: date | None = None) -> dict:
    """把模型常见别名/相对日期归一化为 TripRequest 字段。

    today 允许测试注入固定日期，避免测试结果随运行日期漂移。
    """
    today = today or date.today()

    # 1. 先统一键名，后续只处理 TripRequest 的标准字段。
    data: dict = {}
    for key, value in raw.items():
        data[ALIASES.get(key, key)] = value

    # 2. 日期统一成 ISO；duration 只用于推算缺失的 end_date。
    duration = data.pop("duration_days", None)
    if "start_date" in data:
        data["start_date"] = _parse_relative_date(data["start_date"], today)
    if "end_date" in data:
        data["end_date"] = _parse_relative_date(data["end_date"], today)

    # “出差两天”通常对应 start_date + 1 天结束（两天一晚）。
    if not data.get("end_date") and data.get("start_date"):
        try:
            start = date.fromisoformat(data["start_date"])
            days = int(duration) if duration else 1
            data["end_date"] = (start + timedelta(days=max(days - 1, 0))).isoformat()
        except (ValueError, TypeError):
            # 日期无法解析时保留空值，由后续追问处理。
            pass

    # 3. 模型没明确说不要机票/酒店时，默认两者都需要。
    data.setdefault("need_flight", True)
    data.setdefault("need_hotel", True)
    return data


async def understand(state: dict, deps) -> dict:
    """把自然语言需求转成 TripRequest。

    步骤：
    1. 构造带当天日期的解析提示词并调用轻量模型；
    2. 解析 JSON，兼容代码块和字段别名；
    3. 解析失败转追问，不带着空槽位继续；
    4. 目的地仍为空时追问；
    5. 成功则写回结构化需求。
    """
    # 步骤 1：构造模型上下文和解析提示词。
    ctx = CallContext(
        trace_id=state["trace_id"], tenant_id=state["tenant_id"],
        task_id=state["task_id"], purpose="understand",
    )
    system = SYSTEM_TEMPLATE.format(today=date.today().isoformat())
    try:
        async with deps.span(
            "orchestration.node.understand", "orchestration",
            trace_id=state["trace_id"],
        ):
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": state["request"].get("raw_message", "")},
            ]
            completion = await deps.model.complete(
                ctx, messages, deps.tier_light,
                response_schema=TripRequest.model_json_schema(),
            )
    except Exception:  # noqa: BLE001 - 模型不可用时转人工补充
        human = HumanRequest(
            type=HumanRequestType.CLARIFY,
            message="模型服务暂时不可用，请稍后重试。",
        )
        return {"status": "WAITING_HUMAN",
                "pending_human": human.model_dump(mode="json")}

    # 步骤 2/3：解析并归一化；失败转追问。
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

    # 步骤 4：目的地是硬性槽位，缺失则追问。
    if not request.destination_city:
        human = HumanRequest(type=HumanRequestType.CLARIFY, message="请提供目的地。")
        return {"status": "WAITING_HUMAN",
                "pending_human": human.model_dump(mode="json")}
    # 步骤 5：写回结构化需求，进入后续规划。
    return {"request": request.model_dump(mode="json"), "status": "EXECUTING"}
