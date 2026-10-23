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
