from itinerary_agent.adapters.scripted_model import ScriptedModelGateway
from itinerary_agent.domain.models import RequestContext
from itinerary_agent.infra.container import build_container
from tests.db_utils import make_test_settings


async def test_checkpoint_survives_container_restart(tmp_path):
    # 两个容器共享同一个 PostgreSQL，验证任务能从 Checkpoint 恢复。
    settings = make_test_settings()

    c1 = build_container(settings)
    c1.model = ScriptedModelGateway([
        '{"origin_city":"上海","destination_city":"北京","start_date":"2026-11-03","end_date":"2026-11-05"}',
        '{"steps":["search_flights","search_hotels"]}',
        '方案已生成。',
    ])
    await c1.start()
    ctx = RequestContext(
        trace_id="t", tenant_id="demo-company", user_id="u001", session_id="s"
    )
    events = [event async for event in c1.orchestrator.start_turn(ctx, "去北京出差")]
    task_id = events[0].data["task_id"]
    await c1.stop()

    c2 = build_container(settings)
    await c2.start()
    state = await c2.orchestrator.graph.aget_state(
        {"configurable": {"thread_id": task_id}}
    )
    assert state.values["options"]["flights"]
    assert state.next
    await c2.stop()
