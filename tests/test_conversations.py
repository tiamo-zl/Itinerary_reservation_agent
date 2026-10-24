"""对话记录页：全量会话列表与详情。"""

from fastapi.testclient import TestClient

from tests.scenarios import make_app, post_sse, task_id_of


async def test_conversations_list_and_detail(tmp_path):
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        events = post_sse(
            client, "/chat",
            {"message": "下周二去北京", "session_id": "conversation-1"},
            "u002",
        )
        task_id = task_id_of(events)

        listed = client.get(
            "/conversations", headers={"X-Mock-User": "u002"}
        ).json()["conversations"]
        item = next(row for row in listed if row["session_id"] == "conversation-1")
        assert item["user_id"] == "u002"
        assert item["latest_task"]["task_id"] == task_id

        detail = client.get(
            "/conversations/conversation-1", headers={"X-Mock-User": "u002"}
        ).json()
        assert detail["session_id"] == "conversation-1"
        assert detail["messages"]
        assert detail["tasks"][0]["task_id"] == task_id
        assert detail["latest_state"]["values"]["session_id"] == "conversation-1"

        # 员工不能读取他人的会话详情。
        forbidden = client.get(
            "/conversations/conversation-1", headers={"X-Mock-User": "u001"}
        )
        assert forbidden.status_code == 403
