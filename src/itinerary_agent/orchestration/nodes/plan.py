"""任务拆解节点：TripRequest → 执行步骤列表。"""

import json

from itinerary_agent.domain.models import CallContext

SYSTEM = "根据差旅需求生成执行步骤。只输出 {\"steps\": [\"...\"]}。"


async def plan(state: dict, deps) -> dict:
    ctx = CallContext(
        trace_id=state["trace_id"], tenant_id=state["tenant_id"],
        task_id=state["task_id"], purpose="plan",
    )
    async with deps.span("orchestration.node.plan", "orchestration"):
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(state["request"], ensure_ascii=False)},
        ]
        completion = await deps.model.complete(ctx, messages, deps.tier_reasoning)

    steps = json.loads(completion.text).get("steps", [])
    return {"plan": steps, "status": "EXECUTING"}
