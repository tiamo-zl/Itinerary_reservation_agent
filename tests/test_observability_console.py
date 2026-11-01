"""观测控制台相关 API：trace 列表/概览、状态历史、反馈回流。"""

from fastapi.testclient import TestClient

from tests.scenarios import (
    make_app,
    post_sse,
    task_id_of,
)


async def test_trace_and_badcase_apis(tmp_path):
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        events = post_sse(
            client, "/chat",
            {"message": "下周二去北京出差两天，预算 1000 元"},
            "u002",
        )
        status = events[0]["data"]
        task_id = task_id_of(events)
        trace_id = status["trace_id"]
        assert trace_id

        admin = {"X-Mock-User": "u002"}
        task = client.get(f"/tasks/{task_id}", headers=admin).json()
        assert task["trace_id"] == trace_id

        # 状态级回放：Checkpoint 历史应包含至少一个快照。
        history = client.get(
            f"/tasks/{task_id}/history", headers=admin
        ).json()
        assert history["history"]

        traces = client.get("/traces", headers=admin).json()["traces"]
        assert any(item["trace_id"] == trace_id for item in traces)

        task_summary = client.get("/tasks/summary", headers=admin).json()["tasks"]
        summary = next(item for item in task_summary if item["task_id"] == task_id)
        assert summary["trace_count"] >= 1
        assert summary["span_count"] > 0

        task_traces = client.get(
            f"/tasks/{task_id}/traces", headers=admin
        ).json()["traces"]
        assert task_traces[0]["trace_id"] == trace_id
        assert task_traces[0]["span_count"] > 0

        overview = client.get("/traces/overview", headers=admin).json()
        assert overview["totals"]["traces"] >= 1
        assert overview["layers"]

        detail = client.get(f"/traces/{trace_id}", headers=admin).json()
        assert detail["task_id"] == task_id
        assert detail["spans"]

        feedback = client.post("/feedback", json={
            "trace_id": trace_id,
            "task_id": task_id,
            "category": "plan",
            "severity": "high",
            "user_input": "联系我 13812345678",
            "expected": "应该先查询酒店",
            "actual": "直接给出方案",
        }, headers={"X-Mock-User": "u002"})
        assert feedback.status_code == 200
        badcase_id = feedback.json()["badcase_id"]

        forbidden = client.get("/badcases", headers={"X-Mock-User": "u001"})
        assert forbidden.status_code == 403

        listed = client.get("/badcases", headers={"X-Mock-User": "u002"}).json()
        row = next(item for item in listed["badcases"] if item["badcase_id"] == badcase_id)
        assert row["status"] == "open"
        assert "13812345678" not in row["user_input"]

        updated = client.patch(
            f"/badcases/{badcase_id}",
            headers={"X-Mock-User": "u002"},
            json={"status": "reproduced", "root_cause": "plan prompt"},
        )
        assert updated.status_code == 200
        listed = client.get(
            "/badcases?status=reproduced", headers={"X-Mock-User": "u002"}
        ).json()
        assert listed["badcases"][0]["badcase_id"] == badcase_id
