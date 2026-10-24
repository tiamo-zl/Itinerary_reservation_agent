"""下单节点：写操作，必须已确认且通过 guard。"""

from itinerary_agent.domain.models import HumanRequest, HumanRequestType


async def book(state: dict, deps) -> dict:
    selected = state.get("selected", {})

    async with deps.span(
        "orchestration.node.book", "orchestration",
        trace_id=state["trace_id"],
    ):
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

    return {"status": "COMPLETED"}
