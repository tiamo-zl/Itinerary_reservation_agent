"""请求上下文构造与本地 mock 鉴权。

生产环境由 auth 中间件解析 JWT/OIDC；mock 模式用请求头映射本地用户。
两种模式最终都落到同一个 RequestContext 形状。
"""

import re
from uuid import uuid4

from fastapi import Request

from itinerary_agent.domain.models import RequestContext
from itinerary_agent.security.scopes import scopes_for_roles

MOCK_USERS = {
    "u001": {"tenant_id": "demo-company", "roles": ["employee"]},
    "u002": {"tenant_id": "demo-company", "roles": ["employee", "approver"]},
    "u003": {"tenant_id": "other-company", "roles": ["employee"]},
}

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def request_id_of(request: Request) -> str:
    """接受安全的 X-Request-ID，否则生成新的 UUID。"""
    value = request.headers.get("X-Request-ID")
    if value and _REQUEST_ID.match(value):
        return value
    return uuid4().hex


def mock_context(request: Request,
                 request_id: str | None = None) -> RequestContext:
    """本地 mock 鉴权：X-Mock-User → 用户/租户/角色。"""
    user_id = request.headers.get("X-Mock-User", "u001")
    mock = MOCK_USERS.get(user_id, MOCK_USERS["u001"])
    roles = list(mock["roles"])
    return RequestContext(
        trace_id=request.headers.get("X-Trace-Id") or uuid4().hex,
        tenant_id=mock["tenant_id"],
        user_id=user_id,
        roles=roles,
        scopes=scopes_for_roles(roles),
        auth_method="mock",
        request_id=request_id or request_id_of(request),
        session_id=request.headers.get("X-Session-Id", "default-session"),
    )


def build_context(request: Request,
                  session_id: str | None = None) -> RequestContext:
    """取中间件已认证的上下文；没有时回退到 mock（便于直接调用/测试）。

    请求体里的 session_id 优先级最高，其次是 X-Session-Id。
    """
    ctx = getattr(request.state, "ctx", None) or mock_context(request)
    return ctx.model_copy(update={
        "session_id": (
            session_id
            or request.headers.get("X-Session-Id", ctx.session_id)
        )
    })
