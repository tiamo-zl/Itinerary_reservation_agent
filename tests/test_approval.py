from itinerary_agent.adapters.mock.approval import MockApprovalSystem
from itinerary_agent.infra.db import Database


async def test_approval_can_be_rejected(tmp_path):
    # 演示审批驳回分支；delay=999 表示不自动通过。
    db = Database(tmp_path / "a.db")
    await db.connect()
    approval = MockApprovalSystem(db, auto_approve_delay=999)
    ref = await approval.submit("t1", 1, {"plan": "x"})
    assert ref.status.value == "pending"

    await approval.decide(ref.approval_id, "rejected", "超标")
    updated = await approval.get(ref.approval_id)
    assert updated.status.value == "rejected"
    assert updated.comment == "超标"
    await db.close()
