"""人类确认节点。

使用 LangGraph interrupt 暂停任务并保存现场；用户恢复后，
节点会从开头重新执行，interrupt() 返回用户提交的 Decision。
"""

from langgraph.types import interrupt

from itinerary_agent.domain.models import HumanRequest, HumanRequestType


async def confirm(state: dict, deps) -> dict:
    """人工确认节点。

    步骤：
    1. 已完成确认则直接放行；
    2. 组合差标/驳回原因生成提示语；
    3. 汇总机票和酒店方案及 warn 提示；
    4. 组装 confirm interrupt 并暂停；
    5. 恢复后处理取消/修改/选择，未选择则默认第一个。
    """
    # 步骤 1：已经确认过（例如审批后再次进入）直接继续。
    if state.get("confirmed"):
        return {"status": "EXECUTING"}

    async with deps.span(
        "orchestration.node.confirm", "orchestration",
        trace_id=state["trace_id"],
    ):
        # 步骤 2：确定提示语优先级。
        message = "请确认方案后继续下单。"
        if state.get("pending_human"):
            message = state["pending_human"].get("message", message)
        policy = state.get("policy_result") or {}
        # pending_human（如审批驳回原因）优先于通用差标提示。
        if not state.get("pending_human") and policy.get("passed") is False:
            message = "方案不符合差标，请修改预算/选项，或取消本次任务。"

        # 步骤 3：汇总候选方案和 warn 提示，避免“确认什么”不可见。
        options = state.get("options", {})
        summarize = []
        for flight in options.get("flights", []):
            summarize.append(
                f"{flight.get('flight_no', flight.get('option_id'))} "
                f"{flight.get('price')}"
            )
        for hotel in options.get("hotels", []):
            summarize.append(
                f"{hotel.get('hotel_name', hotel.get('option_id'))} "
                f"{hotel.get('price_per_night')}/晚"
            )
        if summarize:
            message += " " + "；".join(summarize)
        warnings = [
            violation["message"]
            for violation in policy.get("violations", [])
            if violation.get("severity") == "warn"
        ]
        if warnings:
            message += "。提示：" + "；".join(warnings)

        # 机票和酒店一起交给前端，避免只有酒店时确认弹窗为空。
        confirm_options = [
            {"option_type": "flight", **flight}
            for flight in options.get("flights", [])
        ] + [
            {"option_type": "hotel", **hotel}
            for hotel in options.get("hotels", [])
        ]

    # 步骤 4：interrupt 在 span 外调用，人工等待期间不占用 span。
    decision = interrupt(
        HumanRequest(
            type=HumanRequestType.CONFIRM_OPTION,
            message=message,
            options=confirm_options,
        ).model_dump(mode="json")
    )

    # 步骤 5：处理恢复后的用户决策。
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
