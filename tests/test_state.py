from itinerary_agent.domain.models import GuardResult, PolicyResult, TaskStatus, TripRequest


def test_trip_request_defaults():
    # 未显式指定时，默认同时需要机票和酒店。
    r = TripRequest(destination_city="北京", start_date="2026-11-03", end_date="2026-11-05")
    assert r.need_flight is True
    assert r.need_hotel is True


def test_policy_result_and_guard():
    p = PolicyResult(passed=False, requires_approval=True, policy_version="2026.1")
    assert p.violations == []
    g = GuardResult(allowed=False, code="APPROVAL_REQUIRED", message="need approval")
    assert g.allowed is False
    assert TaskStatus.PLANNING.value == "PLANNING"
