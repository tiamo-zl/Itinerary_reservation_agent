from langgraph.checkpoint.memory import MemorySaver

from itinerary_agent.domain.models import RequestContext
from tests.fakes import ScriptedDeps


async def test_understand_plan_and_search():
    deps = ScriptedDeps(checkpointer=MemorySaver())
    service = deps.build_service()
    ctx = RequestContext(
        trace_id="t1", tenant_id="demo-company", user_id="u001",
        session_id="s1", roles=["employee"],
    )

    events = [event async for event in service.start_turn(ctx, "下周二去北京出差两天")]
    # 搜索后会进入人类确认；完整完成路径由 test_hitl 覆盖。
    assert any(event.type == "interrupt" for event in events)
