"""审批节点：提交审批单并中断，等待审批结果恢复。

submit_approval 是写操作，先经过 guard；审批结果由轮询器/回调恢复。
"""

from langgraph.types import interrupt

from itinerary_agent.domain.models import HumanRequest, HumanRequestType


async def request_approval(state: dict, deps) -> dict:
    # span 在 interrupt 前结束，避免审批等待期间一直挂着一个未完成的 span。
    async with deps.span(
        "orchestration.node.approval", "orchestration",
        trace_id=state["trace_id"],
    ):
        result = await deps.guarded_invoke(
            state, "submit_approval", "submit_approval",
            {
                "task_id": state["task_id"],
                "revision": state["revision"],
                "payload": {
                    "request": state["request"],
                    "options": state["options"],
                    "policy_result": state.get("policy_result"),
                    "revision": state["revision"],
                },
            },
        )
    if not result.ok:
        return {"status": "FAILED", "error": result.error.model_dump()}

    approval = result.data
    decision = interrupt({
        "kind": "approval",
        "approval_id": approval["approval_id"],
        "message": "等待审批结果。",
    })

    status = (decision or {}).get("status", "pending")
    approval = {**approval, "status": status}
    if status == "rejected":
        human = HumanRequest(
            type=HumanRequestType.APPROVAL_REJECTED,
            message=(decision or {}).get("comment", "审批驳回，请修改方案。"),
        )
        return {
            "approval": approval,
            "status": "WAITING_HUMAN",
            "pending_human": human.model_dump(mode="json"),
        }
    return {"approval": approval, "status": "EXECUTING"}
