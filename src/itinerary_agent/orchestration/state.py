"""LangGraph 任务状态。

状态必须保持 JSON 可序列化：Checkpoint 会把它写入 SQLite。
节点内部需要 Pydantic 模型时，用 model_validate 临时转换，不要把模型实例放回状态。
"""

from typing import TypedDict
from uuid import uuid4

from itinerary_agent.domain.models import RequestContext


class TravelTaskState(TypedDict, total=False):
    task_id: str
    trace_id: str
    tenant_id: str
    user_id: str
    session_id: str
    roles: list[str]
    scopes: list[str]
    status: str
    revision: int
    request: dict
    plan: list[str]
    options: dict
    selected: dict
    confirmed: bool
    policy_result: dict | None
    policy_refs: list[str]
    approval: dict | None
    pending_human: dict | None
    pending_amendment: dict | None
    error: dict | None
    summary: str
    schema_version: int


def initial_state(ctx: RequestContext, message: str) -> TravelTaskState:
    """创建一轮对话的初始状态。

    raw_message 只用于 understand 节点；结构化字段解析后写入 request，
    后续节点不再依赖原始自然语言。
    """
    return {
        "task_id": uuid4().hex,
        "trace_id": ctx.trace_id,
        "tenant_id": ctx.tenant_id,
        "user_id": ctx.user_id,
        "session_id": ctx.session_id,
        # 角色/scope 随任务固化，恢复和 worker 路径不再依赖请求头。
        "roles": list(getattr(ctx, "roles", []) or []),
        "scopes": list(getattr(ctx, "scopes", []) or []),
        "status": "PLANNING",
        "revision": 0,
        "request": {"raw_message": message},
        "plan": [],
        "options": {"flights": [], "hotels": []},
        "selected": {},
        "confirmed": False,
        "policy_result": None,
        "policy_refs": [],
        "approval": None,
        "pending_human": None,
        "pending_amendment": None,
        "error": None,
        "summary": "",
        "schema_version": 1,
    }
