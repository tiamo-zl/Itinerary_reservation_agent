"""任务拆解节点：TripRequest → 执行步骤列表。"""

import json

from itinerary_agent.domain.models import CallContext

SYSTEM = (
    "根据差旅需求生成执行步骤。只输出一个 JSON 对象，格式为 "
    '{"steps":["search_flights","search_hotels"]}，不要 Markdown，不要解释。'
)


async def plan(state: dict, deps) -> dict:
    """生成执行计划。

    步骤：
    1. 先检索制度，得到 citation 引用；
    2. 调模型生成步骤建议；
    3. 解析 JSON；失败时降级为默认查询步骤。
    """
    # 步骤 1：规划前检索制度依据；状态只保存引用 ID。
    refs: list[str] = []
    if deps.knowledge is not None:
        async with deps.span(
            "knowledge.search_policy", "knowledge",
            tenant_id=state["tenant_id"], trace_id=state["trace_id"],
        ):
            context = await deps.knowledge.search_policy(
                deps.ctx_of(state), "差旅住宿与机票标准"
            )
        refs = [clause.clause_id for clause in context.clauses]

    # 步骤 2：调用大模型生成计划。
    ctx = CallContext(
        trace_id=state["trace_id"], tenant_id=state["tenant_id"],
        task_id=state["task_id"], purpose="plan",
    )
    completion = None
    try:
        async with deps.span(
            "orchestration.node.plan", "orchestration",
            trace_id=state["trace_id"],
        ):
            messages = [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(
                    state["request"], ensure_ascii=False
                )},
            ]
            completion = await deps.model.complete(
                ctx, messages, deps.tier_reasoning
            )
    except Exception:  # noqa: BLE001 - 模型不可用时使用默认步骤
        completion = None

    # 步骤 3：模型输出只用于“建议步骤”，不是执行依据；
    # 解析失败时退化为默认查询步骤，后续 search/policy 仍按确定性代码执行。
    try:
        text = completion.text.strip() if completion is not None else ""
        start, end = text.find("{"), text.rfind("}")
        steps = json.loads(text[start:end + 1]).get("steps", [])
    except Exception:  # noqa: BLE001 - 模型输出不可信，解析失败需降级
        steps = ["search_flights", "search_hotels"]
    return {"plan": steps, "status": "EXECUTING", "policy_refs": refs}
