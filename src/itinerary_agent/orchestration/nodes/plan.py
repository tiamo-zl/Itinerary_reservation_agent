"""任务拆解节点：TripRequest → 执行步骤列表。"""

import json

from itinerary_agent.domain.models import CallContext

SYSTEM = "根据差旅需求生成执行步骤。只输出 {\"steps\": [\"...\"]}。"


async def plan(state: dict, deps) -> dict:
    # 规划前检索制度依据；图状态只保存引用 ID，不保存制度原文。
    refs: list[str] = []
    if deps.knowledge is not None:
        context = await deps.knowledge.search_policy(
            deps.ctx_of(state), "差旅住宿与机票标准"
        )
        refs = [clause.clause_id for clause in context.clauses]

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
    return {"plan": steps, "status": "EXECUTING", "policy_refs": refs}
