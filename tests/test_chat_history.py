"""会话历史：用户消息与助手总结需要落库并可重新加载。"""

from fastapi.testclient import TestClient

from tests.scenarios import last_event, make_app, post_sse, task_id_of


async def test_chat_history_roundtrip(tmp_path):
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        events = post_sse(
            client, "/chat",
            {"message": "下周二去北京", "session_id": "session-1"},
            "u002",
        )
        task_id = task_id_of(events)
        assert last_event(events, "interrupt")

        first = client.get("/sessions/session-1/messages").json()["messages"]
        assert first[-1]["role"] == "user"
        assert "北京" in first[-1]["content"]

        resumed = post_sse(
            client, f"/tasks/{task_id}/resume",
            {"action": "select", "selected": {"flight_id": "f2", "hotel_id": "h1"}},
            "u002",
        )
        assert last_event(resumed, "result")["data"]["status"] == "COMPLETED"

        second = client.get("/sessions/session-1/messages").json()["messages"]
        assert [message["role"] for message in second[-2:]] == ["user", "assistant"]
        assert second[-1]["content"]
