from langgraph.checkpoint.memory import MemorySaver

from itinerary_agent.adapters.scripted_model import ScriptedModelGateway
from itinerary_agent.domain.models import Decision, RequestContext, TripRequest
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


async def test_modify_replans_with_new_revision():
    # 修改需求后应清空旧结果、revision++，并重新规划。
    deps = ScriptedDeps(checkpointer=MemorySaver())
    deps.model = ScriptedModelGateway([
        '{"origin_city":"上海","destination_city":"北京","start_date":"2026-11-03","end_date":"2026-11-05"}',
        '{"steps":["search_flights","search_hotels"]}',
        '{"steps":["search_flights","search_hotels"]}',
    ])
    service = deps.build_service()
    ctx = RequestContext(
        trace_id="t", tenant_id="demo-company", user_id="u001", session_id="s"
    )
    events = [event async for event in service.start_turn(ctx, "去北京")]
    task_id = next(event for event in events if event.type == "interrupt").data["task_id"]

    async for _ in service.resume(
        ctx, task_id,
        Decision(action="modify", amended_request=TripRequest(destination_city="上海")),
    ):
        pass

    state = await service.graph.aget_state(
        {"configurable": {"thread_id": task_id}}
    )
    # 初始 revision 为 0，修改一次后变为 1。
    assert state.values["revision"] == 1
    assert state.values["request"]["destination_city"] == "上海"
    # 图状态在 confirm 节点暂停；等待状态由任务索引/网关事件表达。
    assert state.next
