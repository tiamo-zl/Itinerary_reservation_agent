from itinerary_agent.adapters.scripted_model import ScriptedModelGateway
from itinerary_agent.domain.models import RequestContext
from itinerary_agent.orchestration.service import OrchestrationService


async def test_understand_plan_and_respond():
    # 脚本化模型按调用顺序返回：需求解析 → 计划 → 总结。
    model = ScriptedModelGateway([
        '{"destination_city":"北京","start_date":"2026-11-03","end_date":"2026-11-05"}',
        '{"steps":["search_flights","search_hotels"]}',
        '已完成行程规划。',
    ])
    service = OrchestrationService(
        model=model, traces=None, tools=None, knowledge=None, control=None
    )
    ctx = RequestContext(
        trace_id="t1", tenant_id="demo-company", user_id="u001",
        session_id="s1", roles=["employee"],
    )
    events = [event async for event in service.start_turn(ctx, "下周二去北京出差两天")]
    assert events[-1].type == "result"
    assert events[-1].data["status"] == "COMPLETED"
