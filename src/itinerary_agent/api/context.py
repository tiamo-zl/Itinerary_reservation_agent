"""请求上下文构造与本地 mock 鉴权。

生产环境应由真实鉴权中间件解析 token；demo 用请求头映射 mock 用户，
但上下文对象的形状与生产保持一致。
"""

from uuid import uuid4

from fastapi import Request

from itinerary_agent.domain.models import RequestContext

MOCK_USERS = {
    "u001": {"tenant_id": "demo-company", "roles": ["employee"]},
    "u002": {"tenant_id": "demo-company", "roles": ["employee", "approver"]},
    "u003": {"tenant_id": "other-company", "roles": ["employee"]},
}


def build_context(request: Request, session_id: str | None = None) -> RequestContext:
    """从请求头构造上下文。

    - X-Mock-User：模拟当前用户，默认 u001
    - X-Trace-Id：允许调用方传入 trace，便于跨系统串联
    - X-Session-Id：会话 ID，优先使用请求体中的 session_id
    """
    user_id = request.headers.get("X-Mock-User", "u001")
    mock = MOCK_USERS.get(user_id, MOCK_USERS["u001"])
    return RequestContext(
        trace_id=request.headers.get("X-Trace-Id") or uuid4().hex,
        tenant_id=mock["tenant_id"],
        user_id=user_id,
        roles=mock["roles"],
        session_id=session_id or request.headers.get("X-Session-Id", "default-session"),
    )
