"""动作准入判断。

这是写操作的最后一道确定性闸门：模型可以建议动作，但只有这里的条件
全部满足，工具层才会真正执行。
"""

from itinerary_agent.domain.models import ApprovalStatus, GuardResult, TaskSnapshot, TaskStatus

READ_TOOLS = {
    "get_user_profile",
    "get_policy_rules",
    "get_visa_requirements",
    "get_approval_status",
}


def guard_action(action: str, snapshot: TaskSnapshot,
                 roles: list[str]) -> GuardResult:
    # 步骤 1：终态任务不再允许任何动作，避免完成后又被改状态。
    if snapshot.status in {
        TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.COMPLETED,
    }:
        return GuardResult(allowed=False, code="GUARD_DENIED", message="任务已结束")

    # 步骤 2：只读动作不改变外部状态，直接放行。
    if action.startswith("search_") or action in READ_TOOLS:
        return GuardResult(allowed=True, code="OK", message="read allowed")

    # 步骤 3：取消任务本身不涉及差标/审批，直接允许。
    if action == "cancel_task":
        return GuardResult(allowed=True, code="OK", message="cancel allowed")

    # 步骤 4：提交审批前，差标必须是“可通过审批”的状态。
    if action == "submit_approval":
        # 差标硬阻断且不允许审批时，不能提交审批。
        if not snapshot.policy_passed and not snapshot.requires_approval:
            return GuardResult(
                allowed=False, code="POLICY_BLOCKED", message="不可审批",
            )
        return GuardResult(allowed=True, code="OK", message="approval allowed")

    # 步骤 5：下单是高风险写操作，逐项检查确认、差标、审批和状态。
    if action.startswith("book_"):
        if not snapshot.confirmed:
            return GuardResult(
                allowed=False, code="CONFIRMATION_REQUIRED", message="需要用户确认",
            )
        if snapshot.policy_passed is None:
            return GuardResult(
                allowed=False, code="POLICY_BLOCKED", message="未完成差标校验",
            )
        if (snapshot.requires_approval
                and snapshot.approval_status != ApprovalStatus.APPROVED):
            return GuardResult(
                allowed=False, code="APPROVAL_REQUIRED", message="需要审批通过",
            )
        if snapshot.policy_passed is False and not snapshot.requires_approval:
            return GuardResult(
                allowed=False, code="POLICY_BLOCKED", message="差标不允许下单",
            )
        return GuardResult(allowed=True, code="OK", message="booking allowed")

    # 步骤 6：未知动作默认拒绝（fail-closed）。
    return GuardResult(allowed=False, code="GUARD_DENIED", message="未知动作")
