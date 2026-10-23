from langgraph.checkpoint.memory import MemorySaver

from itinerary_agent.domain.models import RequestContext
from tests.fakes import ScriptedDeps


async def test_search_node_fills_options():
    deps = ScriptedDeps(checkpointer=MemorySaver())
    service = deps.build_service()
    ctx = RequestContext(
        trace_id="t", tenant_id="demo-company", user_id="u001", session_id="s"
    )

    events = [event async for event in service.start_turn(ctx, "去北京出差")]
    final = await service.graph.aget_state(
        {"configurable": {"thread_id": events[0].data["task_id"]}}
    )
    assert len(final.values["options"]["flights"]) == 2
    assert len(final.values["options"]["hotels"]) == 2
