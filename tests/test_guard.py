from itinerary_agent.control.guard import guard_action
from itinerary_agent.control.rules import PolicyRules
from itinerary_agent.control.service import ControlService
from itinerary_agent.domain.models import ApprovalStatus, TaskSnapshot, TaskStatus


class _NoopAudit:
    async def record(self, *args, **kwargs):
        return None


def test_book_requires_confirmation():
    snapshot = TaskSnapshot(
        task_id="t", status=TaskStatus.EXECUTING, revision=1,
        policy_passed=True, confirmed=False,
    )
    result = guard_action("book_flight", snapshot, roles=["employee"])
    assert result.allowed is False
    assert result.code == "CONFIRMATION_REQUIRED"


def test_book_allowed_when_confirmed_and_approved():
    snapshot = TaskSnapshot(
        task_id="t", status=TaskStatus.EXECUTING, revision=1,
        policy_passed=False, requires_approval=True,
        approval_status=ApprovalStatus.APPROVED, confirmed=True,
    )
    assert guard_action("book_hotel", snapshot, roles=["employee"]).allowed is True


def test_control_service_delegates_policy_and_guard():
    rules = PolicyRules(version="2026.1", tenant_id="demo-company", defaults={}, rules=[])
    service = ControlService(rules, _NoopAudit())
    snapshot = TaskSnapshot(
        task_id="t", status=TaskStatus.EXECUTING, revision=1,
        policy_passed=True, confirmed=False,
    )
    ctx = type("Ctx", (), {"roles": ["employee"]})()
    assert service.guard(ctx, "book_flight", snapshot).code == "CONFIRMATION_REQUIRED"
