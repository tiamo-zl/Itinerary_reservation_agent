"""下单节点：写操作，必须已确认且通过 guard。"""

from itinerary_agent.domain.models import HumanRequest, HumanRequestType


async def book(state: dict, deps) -> dict:
    """执行写操作。

    步骤：
    1. 读取用户确认的机票/酒店；
    2. 机票走 Guard + 幂等键下单；
    3. 酒店走 Guard + 幂等键下单；
    4. 任一失败转人工，全部成功标记 COMPLETED。
    """
    selected = state.get("selected", {})

    async with deps.span(
        "orchestration.node.book", "orchestration",
        trace_id=state["trace_id"],
    ):
        # 步骤 2：机票写操作。
        if selected.get("flight_id"):
            result = await deps.guarded_invoke(
                state, "book_flight", "book_flight",
                {
                    "option_id": selected["flight_id"],
                    "idempotency_key": (
                        f"{state['task_id']}:book_flight:{state['revision']}"
                    ),
                },
            )
            if not result.ok:
                human = HumanRequest(
                    type=HumanRequestType.CLARIFY,
                    message=result.error.message,
                )
                return {
                    "status": "WAITING_HUMAN",
                    "pending_human": human.model_dump(mode="json"),
                }

        # 步骤 3：酒店写操作。
        if selected.get("hotel_id"):
            result = await deps.guarded_invoke(
                state, "book_hotel", "book_hotel",
                {
                    "option_id": selected["hotel_id"],
                    "idempotency_key": (
                        f"{state['task_id']}:book_hotel:{state['revision']}"
                    ),
                },
            )
            if not result.ok:
                human = HumanRequest(
                    type=HumanRequestType.CLARIFY,
                    message=result.error.message,
                )
                return {
                    "status": "WAITING_HUMAN",
                    "pending_human": human.model_dump(mode="json"),
                }

    # 步骤 4：全部写操作成功。
    return {"status": "COMPLETED"}
