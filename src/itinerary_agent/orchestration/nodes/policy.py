"""差标校验节点：只调用确定性控制层，不依赖模型。"""

from itinerary_agent.domain.models import PolicyResult, SearchResults, TripRequest


async def policy_check(state: dict, deps) -> dict:
    request = TripRequest.model_validate(state["request"])
    options = SearchResults.model_validate(state["options"])
    profile = await deps.get_user_profile(state)

    async with deps.span(
        "control.check_policy", "control", tenant_id=state["tenant_id"]
    ):
        result: PolicyResult = deps.control.check_policy(request, options, profile)
    await deps.audit.record(
        state["trace_id"], state["task_id"], state["user_id"], "check_policy",
        state["options"], [violation.rule_id for violation in result.violations],
        result.policy_version, "pass" if result.passed else "block",
        "policy evaluation",
    )
    return {
        "policy_result": result.model_dump(mode="json"),
        "status": "EXECUTING",
    }
