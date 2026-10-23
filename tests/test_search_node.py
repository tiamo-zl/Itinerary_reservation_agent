from itinerary_agent.adapters.mock.inventory import MockFlightInventory, MockHotelInventory
from itinerary_agent.adapters.mock.users import MockUserDirectory
from itinerary_agent.adapters.scripted_model import ScriptedModelGateway
from itinerary_agent.domain.models import RequestContext
from itinerary_agent.orchestration.service import OrchestrationService
from itinerary_agent.tools.builtin import build_builtin_registry
from itinerary_agent.tools.registry import ToolRegistry
from itinerary_agent.tools.service import ToolService


async def test_search_node_fills_options():
    # 查询工具走 mock 库存，验证搜索节点把结果写回图状态。
    registry = build_builtin_registry(
        ToolRegistry(), MockFlightInventory(), MockHotelInventory(), MockUserDirectory()
    )
    model = ScriptedModelGateway([
        '{"origin_city":"上海","destination_city":"北京","start_date":"2026-11-03","end_date":"2026-11-05"}',
        '{"steps":["search_flights","search_hotels"]}',
        '方案已生成。',
    ])
    service = OrchestrationService(
        model=model, traces=None, tools=ToolService(registry),
        knowledge=None, control=None,
    )
    ctx = RequestContext(
        trace_id="t", tenant_id="demo-company", user_id="u001", session_id="s"
    )
    events = [event async for event in service.start_turn(ctx, "去北京出差")]
    final = await service.graph.aget_state(
        {"configurable": {"thread_id": events[0].data["task_id"]}}
    )
    assert len(final.values["options"]["flights"]) == 2
    assert len(final.values["options"]["hotels"]) == 2
