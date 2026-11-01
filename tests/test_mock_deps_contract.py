"""独立 mock 依赖服务的 HTTP 契约。"""

from fastapi.testclient import TestClient

from itinerary_agent.mock_services.deps import create_deps_app


def test_user_inventory_approval_and_booking_contract():
    with TestClient(create_deps_app()) as client:
        user = client.get("/users/u001")
        assert user.status_code == 200
        assert user.json()["employee_level"] == "L2"
        assert client.get("/users/missing").status_code == 404

        flights = client.get(
            "/inventory/flights",
            params={"origin": "上海", "destination": "北京",
                    "date": "2026-11-03"},
        ).json()["flights"]
        assert flights and flights[0]["option_id"] == "f1"

        hotels = client.get(
            "/inventory/hotels",
            params={"city": "北京", "check_in": "2026-11-03",
                    "check_out": "2026-11-05"},
        ).json()["hotels"]
        assert hotels and hotels[0]["price_per_night"] == 480.0

        # 下单幂等：同一 key 第二次标记 replayed。
        first = client.post("/bookings", json={
            "kind": "book_flight", "idempotency_key": "k1",
            "payload": {"option_id": "f1"},
        }).json()
        second = client.post("/bookings", json={
            "kind": "book_flight", "idempotency_key": "k1",
            "payload": {"option_id": "f1"},
        }).json()
        assert first["replayed"] is False
        assert second["replayed"] is True
        assert second["booking_id"] == first["booking_id"]

        # 审批提交按 task_id + revision 幂等。
        submitted = client.post("/approvals", json={
            "task_id": "t1", "revision": 0, "payload": {"amount": 1000},
        }).json()
        again = client.post("/approvals", json={
            "task_id": "t1", "revision": 0, "payload": {"amount": 1000},
        }).json()
        assert submitted["approval_id"] == again["approval_id"]
        assert submitted["status"] == "pending"

        approval_id = submitted["approval_id"]
        decided = client.post(
            f"/approvals/{approval_id}/decide",
            json={"status": "approved", "comment": "ok"},
        )
        assert decided.status_code == 200
        current = client.get(f"/approvals/{approval_id}").json()
        assert current["status"] == "approved"
        assert current["comment"] == "ok"

        pending = client.get("/approvals", params={"status": "pending"}).json()
        assert pending["approvals"] == []


def test_fault_injection_contract():
    with TestClient(create_deps_app()) as client:
        error = client.get(
            "/users/u001", headers={"X-Mock-Fault": "500"}
        )
        assert error.status_code == 500

        limited = client.get(
            "/users/u001", headers={"X-Mock-Fault": "429"}
        )
        assert limited.status_code == 429
        assert limited.headers["Retry-After"] == "1"
