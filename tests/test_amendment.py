from itinerary_agent.domain.models import TripRequest


def test_amendment_clears_downstream():
    # 修改需求后，旧方案/差标/审批/确认必须全部失效。
    from itinerary_agent.orchestration.service import apply_amendment

    state = {
        "revision": 1,
        "request": {"destination_city": "北京"},
        "options": {"flights": [{"option_id": "f1"}], "hotels": []},
        "policy_result": {"passed": True},
        "policy_refs": ["c1"],
        "approval": {"approval_id": "a1"},
        "selected": {"flight_id": "f1"},
        "confirmed": True,
        "status": "EXECUTING",
        "pending_human": {"type": "confirm_option"},
        "error": {"code": "X"},
    }

    updated = apply_amendment(state, TripRequest(destination_city="上海"))
    assert updated["revision"] == 2
    assert updated["options"] == {"flights": [], "hotels": []}
    assert updated["approval"] is None
    assert updated["confirmed"] is False
    assert updated["pending_human"] is None
    assert updated["error"] is None
    assert updated["status"] == "PLANNING"
