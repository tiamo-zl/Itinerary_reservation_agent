"""接入网关路由。

网关只负责：构造上下文、脱敏、调用编排接口、把事件转成 SSE。
它不直接调用工具或模型，也不保存 LangGraph 状态。
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from itinerary_agent.api.context import build_context
from itinerary_agent.api.pii import scrub
from itinerary_agent.api.sse import to_sse
from itinerary_agent.domain.models import Decision


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default-session"


def build_router(container) -> APIRouter:
    router = APIRouter()

    @router.post("/chat")
    async def chat(payload: ChatRequest, request: Request):
        # 请求体里的 session_id 优先级高于请求头；trace 由网关生成或透传。
        ctx = build_context(request, session_id=payload.session_id)
        container.traces.start_trace(ctx.trace_id)

        async def events():
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
            async for event in container.orchestrator.resume(ctx, task_id, decision):
                yield to_sse(event)

        return EventSourceResponse(events())

    @router.get("/tasks/{task_id}")
    async def get_task(task_id: str):
        row = await container.db.fetchone(
            "SELECT task_id, status, revision FROM tasks WHERE task_id = ?",
            (task_id,),
        )
        return dict(row) if row else {"error": "not found"}

    return router
