"""人类确认节点。

使用 LangGraph interrupt 暂停任务并保存现场；用户恢复后，
节点会从开头重新执行，interrupt() 返回用户提交的 Decision。
"""

from langgraph.types import interrupt

from itinerary_agent.domain.models import HumanRequest, HumanRequestType


async def confirm(state: dict, deps) -> dict:
    # 已经确认过（例如未来审批后再次进入）直接继续，避免重复打断。
    if state.get("confirmed"):
        return {"status": "EXECUTING"}

    message = "请确认方案后继续下单。"
    if state.get("pending_human"):
        message = state["pending_human"].get("message", message)
    policy = state.get("policy_result") or {}
    if policy.get("passed") is False:
        message = "方案不符合差标，请修改预算/选项，或取消本次任务。"

    decision = interrupt(
        HumanRequest(
            type=HumanRequestType.CONFIRM_OPTION,
            message=message,
            options=state.get("options", {}).get("flights", []),
        ).model_dump(mode="json")
    )

    if isinstance(decision, dict) and decision.get("action") == "modify":
        return {"status": "PLANNING", "confirmed": False, "pending_human": None}
    if isinstance(decision, dict) and decision.get("action") == "cancel":
        return {"status": "CANCELLED", "pending_human": None}

    selected = decision.get("selected") if isinstance(decision, dict) else None
    if not selected:
        # demo 默认选中第一个候选；真实产品应由用户显式选择。
        options = state.get("options", {})
        flights = options.get("flights", [])
        hotels = options.get("hotels", [])
        selected = {
            "flight_id": flights[0].get("option_id") if flights else None,
            "hotel_id": hotels[0].get("option_id") if hotels else None,
        }

    return {
        "selected": selected,
        "confirmed": True,
        "pending_human": None,
        "status": "EXECUTING",
    }
