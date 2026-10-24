"""编排流转图：静态节点/边 + 本次实际流转时间线。"""

from fastapi.testclient import TestClient

from tests.scenarios import make_app, post_sse, task_id_of


async def test_trace_flow_reuses_trace_on_resume(tmp_path):
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        events = post_sse(
            client, "/chat",
            {"message": "下周二去北京", "session_id": "flow-1"},
            "u002",
        )
        task_id = task_id_of(events)
        trace_id = events[0]["data"]["trace_id"]

        initial = client.get(f"/traces/{trace_id}/flow").json()
        assert initial["nodes"]
        assert initial["edges"]
        assert initial["timeline"][0]["kind"] == "node"
        assert initial["timeline"][0]["node"] == "understand"

        resumed = post_sse(
            client, f"/tasks/{task_id}/resume",
            {"action": "select", "selected": {"flight_id": "f2", "hotel_id": "h1"}},
            "u002",
        )
        assert events[0]["data"]["trace_id"] == trace_id
        assert resumed[0]["data"]["trace_id"] == trace_id

        flow = client.get(f"/traces/{trace_id}/flow").json()
        node_steps = [
            step["node"] for step in flow["timeline"] if step["kind"] == "node"
        ]
        edge_pairs = [
            (step["source"], step["target"])
            for step in flow["timeline"] if step["kind"] == "edge"
        ]
        assert "understand" in node_steps
        assert "book" in node_steps
        assert "respond" in node_steps
        assert ("confirm", "book") in edge_pairs
        assert ("book", "respond") in edge_pairs
