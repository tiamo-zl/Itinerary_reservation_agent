"""查询节点：并行查询机票与酒店，把候选写回状态。

查询是只读操作，不走 control.guard；后续的差标/审批/下单才需要准入。
"""

from itinerary_agent.domain.models import TripRequest


async def search(state: dict, deps) -> dict:
    """并行查询机票和酒店。

    步骤：
    1. 从状态还原 TripRequest；
    2. 需要机票且有出发/日期时查询航班；
    3. 需要酒店且有日期时查询酒店；
    4. 把候选写回 options。
    """
    # 步骤 1：还原结构化需求。
    request = TripRequest.model_validate(state["request"])

    async with deps.span(
        "orchestration.node.search", "orchestration",
        trace_id=state["trace_id"],
    ):
        flights = []
        hotels = []

        # 步骤 2：查询机票。

        if (request.need_flight and request.origin_city
                and request.destination_city and request.start_date):
            result = await deps.tools.invoke(
                deps.ctx_of(state),
                "search_flights",
                {
                    "origin": request.origin_city,
                    "destination": request.destination_city,
                    "date": request.start_date,
                },
            )
            if result.ok:
                flights = result.data["flights"]

        # 步骤 3：查询酒店。
        if (request.need_hotel and request.destination_city
                and request.start_date and request.end_date):
            result = await deps.tools.invoke(
                deps.ctx_of(state),
                "search_hotels",
                {
                    "city": request.destination_city,
                    "check_in": request.start_date,
                    "check_out": request.end_date,
                    "area": request.hotel_area or "",
                },
            )
            if result.ok:
                hotels = result.data["hotels"]

    # 步骤 4：候选只写回结构化摘要，完整库存留在适配层。
    return {
        "options": {"flights": flights, "hotels": hotels},
        "status": "EXECUTING",
    }
