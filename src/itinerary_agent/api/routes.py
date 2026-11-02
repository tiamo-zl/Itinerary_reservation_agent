"""接入网关路由。

Controller 只做三件事：解析 HTTP/SSE、构造 RequestContext、调用应用服务。
数据访问在 infra/repositories，权限与组合在 application；
这一层不直接访问数据库，也不写查询语句。
"""

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from itinerary_agent.api.context import build_context
from itinerary_agent.api.pii import scrub
from itinerary_agent.api.sse import to_sse
from itinerary_agent.application.access import require_scope
from itinerary_agent.domain.models import Decision, Event
from itinerary_agent.observability.metrics import SSE_CONNECTIONS

logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default-session"


class AdminDecision(BaseModel):
    comment: str = ""


class FeedbackRequest(BaseModel):
    trace_id: str
    task_id: str | None = None
    category: Literal[
        "understand", "plan", "tool", "policy", "rag",
        "approval", "booking", "other",
    ] = "other"
    severity: Literal["low", "medium", "high"] = "medium"
    user_input: str = ""
    expected: str = ""
    actual: str = ""
    comment: str = ""


class BadcaseUpdate(BaseModel):
    status: Literal["open", "reproduced", "fixed", "closed"] | None = None
    root_cause: str | None = None
    comment: str | None = None
    owner: str | None = None
    sla_due_at: str | None = None
    ticket_ref: str | None = None
    regression_suite: Literal[
        "slot", "policy", "retrieval", "approval", "prompt",
    ] | None = None
    regression_case: dict | None = None


def build_router(container) -> APIRouter:
    """注册接入网关的全部路由。

    路由按职责分组：
    - 对话/任务：/chat、resume、任务状态与历史；
    - 会话记录：/conversations、/sessions；
    - 审批：/approvals、/admin/approvals；
    - 反馈回流：/feedback、/badcases；
    - 观测：/tasks/summary、/tasks/{id}/traces、/traces*。
    """
    router = APIRouter()

    def stream(source, route: str, trace_id: str) -> EventSourceResponse:
        """统一 SSE：心跳、断连取消、按轮超时和结构化错误事件。"""

        async def events():
            SSE_CONNECTIONS.inc()
            try:
                async with container.traces.span(
                    "gateway.http", "gateway", route=route
                ):
                    timeout = container.settings.chat_turn_timeout_seconds
                    if timeout and timeout > 0:
                        async with asyncio.timeout(timeout):
                            async for event in source:
                                yield to_sse(event)
                    else:
                        async for event in source:
                            yield to_sse(event)
            except TimeoutError:
                yield to_sse(Event(type="error", data={
                    "trace_id": trace_id,
                    "code": "TURN_TIMEOUT",
                    "message": "本轮执行超时，请稍后重试。",
                }))
            except asyncio.CancelledError:
                # 客户端断连由 sse-starlette/ASGI 取消生成器；不要吞掉。
                raise
            except Exception:
                logger.exception("SSE stream failed")
                yield to_sse(Event(type="error", data={
                    "trace_id": trace_id,
                    "code": "STREAM_FAILED",
                    "message": "服务暂时不可用，请稍后重试。",
                }))
            finally:
                SSE_CONNECTIONS.dec()

        return EventSourceResponse(
            events(),
            ping=container.settings.sse_ping_seconds,
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                # SSE 在中间件返回前就开始写响应，显式返回精确 trace。
                "X-Trace-Id": trace_id,
            },
        )

    # 对话入口：只做上下文、脱敏和 SSE，不持有业务状态。
    @router.post("/chat")
    async def chat(payload: ChatRequest, request: Request):
        # 请求体里的 session_id 优先级高于请求头；trace 由网关生成或透传。
        ctx = build_context(request, session_id=payload.session_id)
        require_scope(ctx, "chat")
        container.traces.start_trace(ctx.trace_id)
        return stream(
            container.orchestrator.start_turn(ctx, scrub(payload.message)),
            "/chat", ctx.trace_id,
        )

    # 人工恢复：复用任务 trace，并把用户决策转成图恢复 payload。
    @router.post("/tasks/{task_id}/resume")
    async def resume(task_id: str, decision: Decision, request: Request):
        # 恢复接口复用任务首次请求的 trace，保证流转图和回放是同一条链。
        # 先确认任务归属，避免同租户其他用户恢复别人的任务。
        ctx = build_context(request)
        trace_id = await container.task_queries.authorize_resume(ctx, task_id)
        if trace_id:
            ctx.trace_id = trace_id
        container.traces.start_trace(ctx.trace_id)
        return stream(
            container.orchestrator.resume(ctx, task_id, decision),
            "/tasks/resume", ctx.trace_id,
        )

    # 观测：任务聚合与按 task 查看 trace。
    @router.get("/tasks/summary")
    async def task_summaries(request: Request, limit: int = 50,
                             cursor: str | None = None):
        return await container.trace_queries.list_task_summaries(
            build_context(request), limit, cursor
        )

    @router.get("/tasks/{task_id}/traces")
    async def task_traces(task_id: str, request: Request):
        return await container.trace_queries.list_task_traces(
            build_context(request), task_id
        )

    @router.get("/tasks/{task_id}")
    async def get_task(task_id: str, request: Request):
        return await container.task_queries.get(build_context(request), task_id)

    # 会话记录：审批人看本租户全部，员工只看自己。
    @router.get("/conversations")
    async def conversations(request: Request, limit: int = 100,
                            cursor: str | None = None):
        return await container.conversation_queries.list_conversations(
            build_context(request), limit, cursor
        )

    @router.get("/conversations/{session_id}")
    async def conversation_detail(session_id: str, request: Request):
        return await container.conversation_queries.detail(
            build_context(request), session_id
        )

    @router.get("/tasks/{task_id}/approvals")
    async def task_approvals(task_id: str, request: Request):
        return await container.approval_queries.list_for_task(
            build_context(request), task_id
        )

    @router.get("/sessions")
    async def sessions(request: Request, limit: int = 50,
                       cursor: str | None = None):
        return await container.conversation_queries.list_sessions(
            build_context(request), limit, cursor
        )

    @router.get("/sessions/{session_id}/messages")
    async def session_messages(session_id: str, request: Request,
                               limit: int = 100):
        return {
            "session_id": session_id,
            "messages": await container.conversation_queries.messages(
                build_context(request), session_id, limit
            ),
        }

    @router.get("/tasks/{task_id}/state")
    async def task_state(task_id: str, request: Request):
        # 供聊天页在审批完成后重新加载待确认中断。
        return await container.task_queries.get_state(
            build_context(request), task_id
        )

    @router.get("/tasks/{task_id}/history")
    async def task_history(task_id: str, request: Request, limit: int = 100):
        # Checkpoint 历史用于“状态级回放”，和 trace 的调用树互补。
        return {
            "task_id": task_id,
            "history": await container.task_queries.get_history(
                build_context(request), task_id, limit
            ),
        }

    # 审批工作台：待办、详情和通过/驳回。
    @router.get("/approvals")
    async def approvals(request: Request, status: str = "pending",
                        limit: int = 50, cursor: str | None = None):
        return await container.approval_queries.list_approvals(
            build_context(request), status, limit, cursor
        )

    @router.get("/approvals/{approval_id}")
    async def approval_detail(approval_id: str, request: Request):
        return await container.approval_queries.get(
            build_context(request), approval_id
        )

    @router.post("/admin/approvals/{approval_id}/approve")
    async def approve(approval_id: str, payload: AdminDecision, request: Request):
        return await container.approval_queries.decide(
            build_context(request), approval_id, "approved", payload.comment
        )

    @router.post("/admin/approvals/{approval_id}/reject")
    async def reject(approval_id: str, payload: AdminDecision, request: Request):
        return await container.approval_queries.decide(
            build_context(request), approval_id, "rejected", payload.comment
        )

    # 反馈回流：入参在网关脱敏，落库交给应用服务。
    @router.post("/feedback")
    async def feedback(payload: FeedbackRequest, request: Request):
        ctx = build_context(request)
        return await container.feedback_service.submit(ctx, {
            "trace_id": payload.trace_id,
            "task_id": payload.task_id,
            "category": payload.category,
            "severity": payload.severity,
            "user_input": scrub(payload.user_input),
            "expected": scrub(payload.expected),
            "actual": scrub(payload.actual),
            "comment": scrub(payload.comment),
        })

    @router.get("/badcases")
    async def list_badcases(request: Request, status: str | None = None,
                            limit: int = 50, cursor: str | None = None):
        return await container.feedback_service.list_badcases(
            build_context(request), status, limit, cursor
        )

    @router.patch("/badcases/{badcase_id}")
    async def update_badcase(badcase_id: str, payload: BadcaseUpdate,
                             request: Request):
        return await container.feedback_service.update(
            build_context(request), badcase_id,
            payload.model_dump(exclude_none=True),
        )

    # Trace 回放与流转图。
    @router.get("/traces")
    async def traces(request: Request, limit: int = 50,
                     cursor: str | None = None):
        return await container.trace_queries.list_traces(
            build_context(request), limit, cursor
        )

    @router.get("/traces/overview")
    async def traces_overview(request: Request):
        # 固定路径必须放在 /traces/{trace_id} 之前。
        return await container.trace_queries.overview(build_context(request))

    @router.get("/traces/{trace_id}/flow")
    async def trace_flow(trace_id: str, request: Request):
        return await container.trace_queries.get_flow(
            build_context(request), trace_id
        )

    @router.get("/traces/{trace_id}")
    async def trace_json(trace_id: str, request: Request):
        return await container.trace_queries.get_trace(
            build_context(request), trace_id
        )

    @router.get("/traces/{trace_id}/view", response_class=HTMLResponse)
    async def trace_view(trace_id: str, request: Request):
        detail = await container.trace_queries.get_trace(
            build_context(request), trace_id
        )

        def render(nodes, depth: int = 0) -> list[str]:
            lines = []
            for node in nodes:
                lines.append(
                    f"<div style='margin-left:{depth * 20}px'>"
                    f"[{node['layer']}] {node['name']} — {node['status']} "
                    f"({node['duration_ms']:.1f}ms)</div>"
                )
                lines.extend(render(node["children"], depth + 1))
            return lines

        return (
            f"<html><body><h2>Trace {trace_id}</h2>"
            + "".join(render(detail["spans"]))
            + "</body></html>"
        )

    return router
