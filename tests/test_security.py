"""P1 安全回归：注入、租户隔离、鉴权头伪造与 PII。"""

from fastapi.testclient import TestClient

from itinerary_agent.api.app import create_app
from itinerary_agent.infra.container import build_container
from tests.db_utils import make_test_settings
from tests.scenarios import last_event, make_app, post_sse, task_id_of


def test_sql_injection_is_stored_as_text_and_queries_still_work(tmp_path):
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        events = post_sse(
            client, "/chat",
            {"message": "下周二去北京", "session_id": "security"},
            "u001",
        )
        task_id = task_id_of(events)
        trace_id = events[0]["data"]["trace_id"]
        assert last_event(events, "interrupt")

        injection = "'; DROP TABLE badcases; --"
        submitted = client.post("/feedback", headers={"X-Mock-User": "u001"}, json={
            "trace_id": trace_id,
            "task_id": task_id,
            "category": "plan",
            "severity": "high",
            "user_input": "联系我 13812345678",
            "comment": injection,
        })
        assert submitted.status_code == 200

        # 表仍然存在，注入文本按普通字段返回，手机号被脱敏。
        listed = client.get("/badcases", headers={"X-Mock-User": "u002"})
        assert listed.status_code == 200
        row = listed.json()["badcases"][0]
        assert row["comment"] == injection
        assert "13812345678" not in row["user_input"]


def test_cross_tenant_task_and_session_access_is_denied(tmp_path):
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        events = post_sse(
            client, "/chat",
            {"message": "下周二去北京", "session_id": "tenant-private"},
            "u001",
        )
        task_id = task_id_of(events)

        assert client.get(
            f"/tasks/{task_id}", headers={"X-Mock-User": "u003"}
        ).status_code == 403
        assert client.get(
            "/sessions/tenant-private/messages",
            headers={"X-Mock-User": "u003"},
        ).status_code == 403
        # approver 可以跨用户读取同租户任务
        assert client.get(
            f"/tasks/{task_id}", headers={"X-Mock-User": "u002"}
        ).status_code == 200


def test_jwt_mode_ignores_mock_user_header(tmp_path):
    settings = make_test_settings(
        auth_mode="jwt",
        jwt_secret="security-secret-0123456789abcdef",
        jwt_issuer="itinerary-agent-local",
        jwt_audience="itinerary-agent",
    )
    app = create_app(build_container(settings))
    with TestClient(app) as client:
        response = client.get(
            "/conversations", headers={"X-Mock-User": "u002"}
        )
    assert response.status_code == 401


def test_sql_payload_in_path_returns_not_found_not_500(tmp_path):
    app, _ = make_app(tmp_path)
    payload = "%27%3B%20DROP%20TABLE%20tasks%3B%20--"
    with TestClient(app) as client:
        response = client.get(
            f"/tasks/{payload}", headers={"X-Mock-User": "u001"}
        )
    assert response.status_code == 404
