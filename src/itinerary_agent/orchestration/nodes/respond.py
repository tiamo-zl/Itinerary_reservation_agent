"""结果汇总节点：生成给用户看的总结，并标记任务完成。"""

from itinerary_agent.domain.models import CallContext

SYSTEM = "用一句中文总结本次差旅方案。"


async def respond(state: dict, deps) -> dict:
    ctx = CallContext(
        trace_id=state["trace_id"], tenant_id=state["tenant_id"],
        task_id=state["task_id"], purpose="summarize",
    )
    async with deps.span("orchestration.node.respond", "orchestration"):
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": str(state.get("request"))},
        ]
        completion = await deps.model.complete(ctx, messages, deps.tier_standard)

    return {"status": "COMPLETED", "summary": completion.text}
