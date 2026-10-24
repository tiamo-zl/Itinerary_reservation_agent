"""确认节点必须告诉员工“确认什么”，包括酒店-only 方案。"""

from fastapi.testclient import TestClient

from tests.scenarios import PLAN, RESPOND, last_event, make_app, post_sse


async def test_confirm_includes_hotel_options(tmp_path):
    understand = (
        '{"destination_city":"北京","start_date":"2026-11-03",'
        '"end_date":"2026-11-05","need_flight":false,"need_hotel":true}'
    )
    app, _ = make_app(tmp_path, script=[understand, PLAN, RESPOND])
    with TestClient(app) as client:
        events = post_sse(client, "/chat", {"message": "去北京住两晚"}, "u002")
        human = last_event(events, "interrupt")["data"]["human_request"]
        assert human["type"] == "confirm_option"
        assert any(
            option.get("option_type") == "hotel" for option in human["options"]
        )
        assert "王府井" in human["message"]
