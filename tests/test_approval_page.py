"""审批页 API：待办列表、审批详情和任务待确认状态。"""

from fastapi.testclient import TestClient

from tests.scenarios import last_event, make_app, post_sse, task_id_of


async def test_approval_page_payload(tmp_path):
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        events = post_sse(
            client, "/chat",
            {"message": "下周二去北京出差两天，住王府井附近，预算 1000 元"},
            "u001",
        )
        task_id = task_id_of(events)
        interrupt = last_event(events, "interrupt")
        approval_id = interrupt["data"]["human_request"]["approval_id"]

        forbidden = client.get("/approvals", headers={"X-Mock-User": "u001"})
        assert forbidden.status_code == 403

        listed = client.get("/approvals", headers={"X-Mock-User": "u002"}).json()
        item = next(row for row in listed["approvals"] if row["approval_id"] == approval_id)
        assert item["task_id"] == task_id
        assert item["payload"]["request"]["destination_city"] == "北京"
        assert item["payload"]["options"]["hotels"]
        assert item["payload"]["policy_result"]["requires_approval"] is True
        assert item["payload"]["policy_result"]["violations"]

        detail = client.get(
            f"/approvals/{approval_id}", headers={"X-Mock-User": "u002"}
        ).json()
        assert detail["approval_id"] == approval_id

        task_approvals = client.get(
            f"/tasks/{task_id}/approvals", headers={"X-Mock-User": "u002"}
        ).json()["approvals"]
        assert task_approvals[0]["approval_id"] == approval_id
        assert task_approvals[0]["payload"]["policy_result"]["violations"]

        state = client.get(f"/tasks/{task_id}/state").json()
        # interrupt 现场在 snapshot.next 中；审批页/聊天页据此判断待办节点。
        assert "approval" in state["next"]

        rejected = client.post(
            f"/admin/approvals/{approval_id}/reject",
            headers={"X-Mock-User": "u002"},
            json={"comment": "超标"},
        )
        assert rejected.status_code == 200
