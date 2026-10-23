from langgraph.checkpoint.memory import MemorySaver

from itinerary_agent.domain.models import Decision, RequestContext
from tests.fakes import ScriptedDeps


async def test_interrupt_and_resume():
    # confirm 节点会中断；恢复后默认选中第一个候选并完成。
    deps = ScriptedDeps(checkpointer=MemorySaver())
    service = deps.build_service()
    ctx = RequestContext(
        trace_id="t", tenant_id="demo-company", user_id="u001", session_id="s"
    )

    events = [event async for event in service.start_turn(ctx, "去北京")]
    interrupt = next(event for event in events if event.type == "interrupt")
    task_id = interrupt.data["task_id"]

    resumed = [
        event async for event in service.resume(ctx, task_id, Decision(action="select"))
    ]
    assert resumed[-1].data["status"] == "COMPLETED"


async def test_cancel_task():
    # 取消是终态：不再恢复图，只返回 CANCELLED。
    deps = ScriptedDeps(checkpointer=MemorySaver())
    service = deps.build_service()
    ctx = RequestContext(
        trace_id="t", tenant_id="demo-company", user_id="u001", session_id="s"
    )
    events = [event async for event in service.start_turn(ctx, "去北京")]
    task_id = next(e for e in events if e.type == "interrupt").data["task_id"]

    resumed = [
        event async for event in service.resume(ctx, task_id, Decision(action="cancel"))
    ]
    assert resumed[-1].data["status"] == "CANCELLED"
