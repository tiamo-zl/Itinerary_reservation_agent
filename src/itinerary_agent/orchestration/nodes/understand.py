"""需求理解节点：自然语言 → TripRequest。"""

import json

from itinerary_agent.domain.models import CallContext, HumanRequest, HumanRequestType, TripRequest

SYSTEM = "你是差旅需求解析器。只输出 JSON，字段与 TripRequest 一致。"


async def understand(state: dict, deps) -> dict:
    ctx = CallContext(
        trace_id=state["trace_id"], tenant_id=state["tenant_id"],
        task_id=state["task_id"], purpose="understand",
    )
    async with deps.span("orchestration.node.understand", "orchestration"):
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": state["request"].get("raw_message", "")},
        ]
        completion = await deps.model.complete(
            ctx, messages, deps.tier_light,
            response_schema=TripRequest.model_json_schema(),
        )

    request = TripRequest.model_validate(json.loads(completion.text))
    if not request.destination_city:
        # 缺少目的地时不继续规划，交给网关转成 interrupt。
        human = HumanRequest(type=HumanRequestType.CLARIFY, message="请提供目的地。")
        return {"status": "WAITING_HUMAN", "pending_human": human.model_dump(mode="json")}
    return {"request": request.model_dump(mode="json"), "status": "EXECUTING"}
