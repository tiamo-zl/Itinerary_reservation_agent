"""内置工具：查询、用户信息与后续的审批/下单。

工具只返回结构化摘要；完整外部数据由适配层按 ID 读取，不进入图状态。
"""

from itinerary_agent.domain.models import ToolSpec

SEARCH_FLIGHTS = ToolSpec(
    name="search_flights",
    description="查询航班",
    side_effect="read",
    risk="low",
    input_schema={
        "type": "object",
        "properties": {
            "origin": {"type": "string"},
            "destination": {"type": "string"},
            "date": {"type": "string"},
        },
        "required": ["origin", "destination", "date"],
    },
    output_schema={"type": "object"},
)

SEARCH_HOTELS = ToolSpec(
    name="search_hotels",
    description="查询酒店",
    side_effect="read",
    risk="low",
    input_schema={
        "type": "object",
        "properties": {
            "city": {"type": "string"},
            "check_in": {"type": "string"},
            "check_out": {"type": "string"},
            "area": {"type": "string"},
        },
        "required": ["city", "check_in", "check_out"],
    },
    output_schema={"type": "object"},
)

GET_USER = ToolSpec(
    name="get_user_profile",
    description="获取用户职级与部门",
    side_effect="read",
    risk="low",
    input_schema={"type": "object", "properties": {}},
    output_schema={"type": "object"},
)


SUBMIT_APPROVAL = ToolSpec(
    name="submit_approval",
    description="提交差旅审批",
    side_effect="write",
    risk="high",
    input_schema={
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "revision": {"type": "integer"},
            "payload": {"type": "object"},
        },
        "required": ["task_id", "revision", "payload"],
    },
    output_schema={"type": "object"},
)

GET_APPROVAL = ToolSpec(
    name="get_approval_status",
    description="查询审批状态",
    side_effect="read",
    risk="low",
    input_schema={
        "type": "object",
        "properties": {"approval_id": {"type": "string"}},
        "required": ["approval_id"],
    },
    output_schema={"type": "object"},
)


BOOK_FLIGHT = ToolSpec(
    name="book_flight",
    description="预订机票",
    side_effect="write",
    risk="high",
    input_schema={
        "type": "object",
        "properties": {
            "option_id": {"type": "string"},
            "idempotency_key": {"type": "string"},
        },
        "required": ["option_id", "idempotency_key"],
    },
    output_schema={"type": "object"},
)

BOOK_HOTEL = ToolSpec(
    name="book_hotel",
    description="预订酒店",
    side_effect="write",
    risk="high",
    input_schema={
        "type": "object",
        "properties": {
            "option_id": {"type": "string"},
            "idempotency_key": {"type": "string"},
        },
        "required": ["option_id", "idempotency_key"],
    },
    output_schema={"type": "object"},
)


def register_booking_tools(registry, booking):
    async def book_flight(ctx, args):
        return await booking.book(
            "book_flight", args["idempotency_key"], args
        )

    async def book_hotel(ctx, args):
        return await booking.book(
            "book_hotel", args["idempotency_key"], args
        )

    registry.register(BOOK_FLIGHT, book_flight)
    registry.register(BOOK_HOTEL, book_hotel)
    return registry


def register_approval_tools(registry, approvals):
    """注册审批相关工具；审批系统由适配器注入。"""

    async def submit_approval(ctx, args):
        ref = await approvals.submit(args["task_id"], args["revision"], args["payload"])
        return ref.model_dump(mode="json")

    async def get_approval_status(ctx, args):
        ref = await approvals.get(args["approval_id"])
        return ref.model_dump(mode="json")

    registry.register(SUBMIT_APPROVAL, submit_approval)
    registry.register(GET_APPROVAL, get_approval_status)
    return registry


def build_builtin_registry(registry, flights, hotels, users):
    """把查询/用户工具注册到 ToolRegistry。

    依赖以参数传入，便于 mock 与真实适配器互换。
    """

    async def search_flights(ctx, args):
        options = await flights.search(
            args["origin"], args["destination"], args["date"]
        )
        return {"flights": [option.model_dump(mode="json") for option in options]}

    async def search_hotels(ctx, args):
        options = await hotels.search(
            args["city"], args["check_in"], args["check_out"], args.get("area")
        )
        return {"hotels": [option.model_dump(mode="json") for option in options]}

    async def get_user_profile(ctx, args):
        profile = await users.get(ctx.user_id)
        return profile.model_dump(mode="json")

    registry.register(SEARCH_FLIGHTS, search_flights)
    registry.register(SEARCH_HOTELS, search_hotels)
    registry.register(GET_USER, get_user_profile)
    return registry
