"""角色到 scope 的映射。

scope 是接口和工具的授权单位；角色只是本地 mock IdP 的便捷来源。
真实 OIDC token 应直接携带 scopes，网关不再用角色推导。
"""

from itinerary_agent.domain.models import RequestContext

ROLE_SCOPES = {
    "employee": {
        "chat", "task:read", "conversation:read",
        "trace:read", "feedback:write",
    },
    "approver": {"approval:read", "approval:decide", "badcase:manage"},
    "admin": {
        "chat", "task:read", "conversation:read", "trace:read",
        "feedback:write", "approval:read", "approval:decide",
        "badcase:manage", "admin",
    },
}

ADMIN_ROLES = {"admin", "approver"}


def scopes_for_roles(roles: list[str]) -> list[str]:
    scopes: set[str] = set()
    for role in roles:
        scopes.update(ROLE_SCOPES.get(role, set()))
    return sorted(scopes)


def effective_scopes(ctx: RequestContext) -> set[str]:
    """优先相信 token scopes；手工构造的上下文再按角色推导。

    approver/admin 是当前系统里的后台角色，授予完整后台 scope；
    这与应用层 `is_admin` 的跨租户读权限保持一致。
    """
    scopes = (
        set(ctx.scopes) if ctx.scopes else set(scopes_for_roles(ctx.roles))
    )
    if ADMIN_ROLES & set(ctx.roles):
        scopes.update(ROLE_SCOPES["admin"])
    return scopes


def has_scope(ctx: RequestContext, scope: str) -> bool:
    return scope in effective_scopes(ctx)
