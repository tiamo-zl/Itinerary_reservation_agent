"""API 加固：CORS、SSE 头部、任务/会话归属。"""

from fastapi.testclient import TestClient

from tests.scenarios import last_event, make_app, post_sse, task_id_of


def test_cors_preflight_is_handled_before_auth(tmp_path):
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        response = client.options(
            "/chat",
            headers={
                "Origin": "http://localhost:5211",
                "Access-Control-Request-Method": "POST",
            },
        )
    assert response.status_code == 200
    assert (
        response.headers["access-control-allow-origin"]
        == "http://localhost:5211"
    )


def test_sse_sets_no_buffering_headers(tmp_path):
    app, _ = make_app(tmp_path)
    with TestClient(app) as client, client.stream(
        "POST", "/chat", json={"message": "下周二去北京"},
        headers={"X-Mock-User": "u001"},
    ) as response:
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-accel-buffering"] == "no"


def test_task_and_session_are_private_to_owner(tmp_path):
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        events = post_sse(
            client, "/chat",
            {"message": "下周二去北京", "session_id": "private"},
            "u001",
        )
        task_id = task_id_of(events)
        assert last_event(events, "interrupt")

        # u003 属于另一个租户，既不能读任务/会话，也不能恢复任务。
        assert client.get(
            f"/tasks/{task_id}", headers={"X-Mock-User": "u003"}
        ).status_code == 403
        assert client.get(
            "/sessions/private/messages", headers={"X-Mock-User": "u003"}
        ).status_code == 403
        assert client.post(
            f"/tasks/{task_id}/resume",
            headers={"X-Mock-User": "u003"},
            json={"action": "cancel"},
        ).status_code == 403

        # 本人可以读到自己的任务。
        assert client.get(
            f"/tasks/{task_id}", headers={"X-Mock-User": "u001"}
        ).status_code == 200
