"""统一权限判断，避免每个 handler 重复写角色/租户判断。"""

from itinerary_agent.application.errors import Forbidden, NotFound
from itinerary_agent.domain.models import RequestContext
from itinerary_agent.security.scopes import ADMIN_ROLES, has_scope


def is_admin(ctx: RequestContext) -> bool:
    return bool(ADMIN_ROLES & set(ctx.roles))


def require_admin(ctx: RequestContext) -> None:
    if not is_admin(ctx):
        raise Forbidden("forbidden")


def require_scope(ctx: RequestContext, scope: str) -> None:
    """scope 是接口/工具的最小授权单位；管理员按角色补齐。"""
    if not has_scope(ctx, scope):
        raise Forbidden("forbidden")


def require_task_access(ctx: RequestContext, task: dict) -> None:
    """管理员可跨任务；普通员工必须同时匹配租户和用户。"""
    if is_admin(ctx):
        return
    if task["tenant_id"] != ctx.tenant_id or task["user_id"] != ctx.user_id:
        raise Forbidden("forbidden")


def require_tenant_access(ctx: RequestContext, record: dict) -> None:
    """按租户隔离数据；管理员跨租户属于显式授权。"""
    if is_admin(ctx):
        return
    if record.get("tenant_id") != ctx.tenant_id:
        raise Forbidden("forbidden")


def require_found(value, name: str = "resource"):
    if value is None:
        raise NotFound(f"{name} not found")
    return value
