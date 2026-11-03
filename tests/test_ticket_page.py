"""模拟工单页：页面可访问，提交后进入本地工单队列。"""

from fastapi.testclient import TestClient

from tests.scenarios import make_app


def test_ticket_page_and_submit(tmp_path):
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        page = client.get("/tickets")
        assert page.status_code == 200
        assert "模拟工单系统" in page.text

        created = client.post(
            "/feedback",
            headers={"X-Mock-User": "u001"},
            json={
                "trace_id": "trace-ticket-demo",
                "task_id": "task-ticket-demo",
                "category": "policy",
                "severity": "high",
                "user_input": "L2 住 800 元酒店",
                "expected": "应触发审批",
                "actual": "直接通过",
                "comment": "ticket page smoke",
            },
        )
        assert created.status_code == 200
        body = created.json()
        assert body["ticket_ref"].startswith("LOCAL-")
        assert body["status"] == "open"
        assert body["sla_due_at"]

        listed = client.get(
            "/badcases", headers={"X-Mock-User": "u002"}
        )
        assert listed.status_code == 200
        rows = listed.json()["badcases"]
        assert any(
            row["badcase_id"] == body["badcase_id"]
            and row["ticket_ref"] == body["ticket_ref"]
            for row in rows
        )
