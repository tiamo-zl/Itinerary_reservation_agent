"""Guard 拒绝 / 下单 / 幂等回放的审计覆盖。"""

from langgraph.checkpoint.memory import MemorySaver

from itinerary_agent.domain.models import RequestContext
from itinerary_agent.orchestration.state import initial_state
from tests.fakes import ScriptedDeps


class CaptureAudit:
    def __init__(self):
        self.records: list[dict] = []

    async def record(self, trace_id, task_id, actor, action, inputs, rule_ids,
                     policy_version, decision, reason):
        self.records.append({
            "trace_id": trace_id, "task_id": task_id, "actor": actor,
            "action": action, "inputs": inputs, "decision": decision,
            "reason": reason,
        })


def _state(ctx: RequestContext, **overrides) -> dict:
    state = initial_state(ctx, "去北京")
    state.update({
        "status": "EXECUTING",
        "confirmed": True,
        "policy_result": {"passed": True, "requires_approval": True},
        "approval": {"status": "pending"},
        **overrides,
    })
    return state


async def test_guard_denial_and_booking_are_audited():
    deps = ScriptedDeps(checkpointer=MemorySaver())
    audit = CaptureAudit()
    deps.audit = audit
    service = deps.build_service()
    ctx = RequestContext(
        trace_id="t", tenant_id="demo-company", user_id="u001",
        session_id="s", roles=["employee"],
    )
    state = _state(ctx)

    # 审批未通过：guard 拒绝，写入 denied 审计。
    denied = await service.guarded_invoke(
        state, "book_flight", "book_flight",
        {"option_id": "f1", "idempotency_key": "k1"},
    )
    assert denied.ok is False
    assert denied.error.code == "APPROVAL_REQUIRED"
    assert audit.records[-1]["decision"] == "denied"
    assert audit.records[-1]["action"] == "book_flight"

    # 审批通过后允许下单；同一幂等键第二次是 replay。
    approved = {**state, "approval": {"status": "approved"}}
    first = await service.guarded_invoke(
        approved, "book_hotel", "book_hotel",
        {"option_id": "h1", "idempotency_key": "k2"},
    )
    second = await service.guarded_invoke(
        approved, "book_hotel", "book_hotel",
        {"option_id": "h1", "idempotency_key": "k2"},
    )
    assert first.ok is True and second.ok is True
    assert audit.records[-2]["decision"] == "allowed"
    assert audit.records[-1]["decision"] == "replayed"


async def test_audit_failure_does_not_break_booking():
    class BrokenAudit:
        async def record(self, *args, **kwargs):
            raise RuntimeError("audit down")

    deps = ScriptedDeps(checkpointer=MemorySaver())
    deps.audit = BrokenAudit()
    service = deps.build_service()
    ctx = RequestContext(
        trace_id="t", tenant_id="demo-company", user_id="u001",
        session_id="s", roles=["employee"],
    )
    state = _state(ctx, approval={"status": "approved"})

    result = await service.guarded_invoke(
        state, "book_flight", "book_flight",
        {"option_id": "f1", "idempotency_key": "k3"},
    )
    assert result.ok is True
