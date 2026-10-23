"""接入网关路由。

网关只负责：构造上下文、脱敏、调用编排接口、把事件转成 SSE。
它不直接调用工具或模型，也不保存 LangGraph 状态。
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from itinerary_agent.api.context import build_context
from itinerary_agent.api.pii import scrub
from itinerary_agent.api.sse import to_sse
from itinerary_agent.domain.models import Decision
from itinerary_agent.observability.query import load_trace_tree


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default-session"


class AdminDecision(BaseModel):
    comment: str = ""


def build_router(container) -> APIRouter:
    router = APIRouter()

    @router.post("/chat")
    async def chat(payload: ChatRequest, request: Request):
        # 请求体里的 session_id 优先级高于请求头；trace 由网关生成或透传。
        ctx = build_context(request, session_id=payload.session_id)
        container.traces.start_trace(ctx.trace_id)

        async def events():
            async with container.traces.span(
                "gateway.http", "gateway", route="/chat"
            ):
                async for event in container.orchestrator.start_turn(
                    ctx, scrub(payload.message)
                ):
                    yield to_sse(event)

        return EventSourceResponse(events())

    @router.post("/tasks/{task_id}/resume")
    async def resume(task_id: str, decision: Decision, request: Request):
        # 恢复接口同样使用 SSE，客户端可以继续看到后续节点进度。
        ctx = build_context(request)
        container.traces.start_trace(ctx.trace_id)

        async def events():
            async with container.traces.span(
                "gateway.http", "gateway", route="/tasks/resume"
            ):
                async for event in container.orchestrator.resume(
                    ctx, task_id, decision
                ):
                    yield to_sse(event)

        return EventSourceResponse(events())

    @router.get("/tasks/{task_id}")
    async def get_task(task_id: str):
        row = await container.db.fetchone(
            "SELECT task_id, status, revision FROM tasks WHERE task_id = ?",
            (task_id,),
        )
        return dict(row) if row else {"error": "not found"}

    @router.post("/admin/approvals/{approval_id}/approve")
    async def approve(approval_id: str, payload: AdminDecision, request: Request):
        ctx = build_context(request)
        if "admin" not in ctx.roles and "approver" not in ctx.roles:
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        row = await container.db.fetchone(
            "SELECT approval_id FROM approvals WHERE approval_id = ?",
            (approval_id,),
        )
        if row is None:
            return JSONResponse(status_code=404, content={"error": "not found"})
        await container.approvals.decide(approval_id, "approved", payload.comment)
        return {"ok": True}

    @router.post("/admin/approvals/{approval_id}/reject")
    async def reject(approval_id: str, payload: AdminDecision, request: Request):
        ctx = build_context(request)
        if "admin" not in ctx.roles and "approver" not in ctx.roles:
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        row = await container.db.fetchone(
            "SELECT approval_id FROM approvals WHERE approval_id = ?",
            (approval_id,),
        )
        if row is None:
            return JSONResponse(status_code=404, content={"error": "not found"})
        await container.approvals.decide(approval_id, "rejected", payload.comment)
        return {"ok": True}

    @router.get("/traces/{trace_id}")
    async def trace_json(trace_id: str):
        return {
            "trace_id": trace_id,
            "spans": await load_trace_tree(container.db, trace_id),
        }

    @router.get("/traces/{trace_id}/view", response_class=HTMLResponse)
    async def trace_view(trace_id: str):
        tree = await load_trace_tree(container.db, trace_id)

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
            + "".join(render(tree))
            + "</body></html>"
        )

    return router
