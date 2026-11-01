"""编排层真流式：respond 的 token 增量进入 SSE 事件。"""

from langgraph.checkpoint.memory import MemorySaver

from itinerary_agent.domain.models import Decision, RequestContext
from tests.fakes import ScriptedDeps


async def test_respond_emits_token_event():
    deps = ScriptedDeps(checkpointer=MemorySaver())
    service = deps.build_service()
    ctx = RequestContext(
        trace_id="stream-trace", tenant_id="demo-company",
        user_id="u001", session_id="stream", roles=["employee"],
    )

    events = [event async for event in service.start_turn(ctx, "去北京")]
    task_id = next(
        event.data["task_id"] for event in events if event.type == "interrupt"
    )

    resumed = [
        event async for event in service.resume(
            ctx, task_id, Decision(action="select")
        )
    ]
    tokens = [event for event in resumed if event.type == "token"]
    assert tokens
    assert tokens[0].data["text"] == "方案已生成。"
    assert tokens[0].data["task_id"] == task_id
    assert tokens[0].data["trace_id"] == "stream-trace"
    assert resumed[-1].type == "result"
    assert resumed[-1].data["status"] == "COMPLETED"
