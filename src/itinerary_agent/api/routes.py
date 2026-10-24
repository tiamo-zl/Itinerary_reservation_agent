"""接入网关路由。

网关只负责：构造上下文、脱敏、调用编排接口、把事件转成 SSE。
它不直接调用工具或模型，也不保存 LangGraph 状态。
"""

import json
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from itinerary_agent.api.context import build_context
from itinerary_agent.api.pii import scrub
from itinerary_agent.api.sse import to_sse
from itinerary_agent.domain.models import Decision
from itinerary_agent.observability.flow import build_flow
from itinerary_agent.observability.query import (
    list_task_summaries,
    list_traces,
    list_traces_for_task,
    load_trace_tree,
    trace_overview,
)


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


def _is_admin(ctx) -> bool:
    return "admin" in ctx.roles or "approver" in ctx.roles


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
        # 恢复接口复用任务首次请求的 trace，保证流转图和回放是同一条链。
        ctx = build_context(request)
        task = await container.db.fetchone(
            "SELECT trace_id FROM tasks WHERE task_id = ?", (task_id,)
        )
        if task and task["trace_id"]:
            ctx.trace_id = task["trace_id"]
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

    @router.get("/tasks/summary")
    async def task_summaries(limit: int = 50):
        return {"tasks": await list_task_summaries(container.db, limit)}

    @router.get("/tasks/{task_id}/traces")
    async def task_traces(task_id: str):
        return {
            "task_id": task_id,
            "traces": await list_traces_for_task(container.db, task_id),
        }

    @router.get("/tasks/{task_id}")
    async def get_task(task_id: str):
        row = await container.db.fetchone(
            "SELECT task_id, trace_id, status, revision, updated_at "
            "FROM tasks WHERE task_id = ?",
            (task_id,),
        )
        return dict(row) if row else {"error": "not found"}

    @router.get("/conversations")
    async def conversations(request: Request, limit: int = 100):
        # 审批人/管理员看全部会话；普通员工只看自己的。
        ctx = build_context(request)
        where = "" if _is_admin(ctx) else "WHERE t.user_id = ?"
        params = () if _is_admin(ctx) else (ctx.user_id,)
        rows = await container.db.fetchall(
            "SELECT m.session_id, COUNT(*) AS message_count, "
            "MAX(m.created_at) AS updated_at, "
            "(SELECT content FROM messages m2 WHERE m2.session_id = m.session_id "
            " ORDER BY m2.id DESC LIMIT 1) AS last_message, "
            "(SELECT role FROM messages m2 WHERE m2.session_id = m.session_id "
            " ORDER BY m2.id DESC LIMIT 1) AS last_role, "
            "MAX(t.user_id) AS user_id, MAX(t.tenant_id) AS tenant_id "
            f"FROM messages m JOIN tasks t ON t.task_id = m.task_id "
            f"{where} GROUP BY m.session_id "
            "ORDER BY updated_at DESC LIMIT ?",
            (*params, limit),
        )
        result = []
        for row in rows:
            item = dict(row)
            latest = await container.db.fetchone(
                "SELECT t.task_id, t.trace_id, t.status, t.revision, t.updated_at "
                "FROM tasks t JOIN messages m ON m.task_id = t.task_id "
                "WHERE m.session_id = ? ORDER BY t.updated_at DESC LIMIT 1",
                (item["session_id"],),
            )
            item["latest_task"] = dict(latest) if latest else None
            result.append(item)
        return {"conversations": result}

    @router.get("/conversations/{session_id}")
    async def conversation_detail(session_id: str, request: Request):
        ctx = build_context(request)
        tasks = await container.db.fetchall(
            "SELECT DISTINCT t.task_id, t.trace_id, t.status, t.revision, "
            "t.updated_at, t.user_id, t.tenant_id "
            "FROM tasks t JOIN messages m ON m.task_id = t.task_id "
            "WHERE m.session_id = ? ORDER BY t.updated_at DESC",
            (session_id,),
        )
        if not tasks:
            return JSONResponse(status_code=404, content={"error": "not found"})
        if not _is_admin(ctx) and all(
            row["user_id"] != ctx.user_id for row in tasks
        ):
            return JSONResponse(status_code=403, content={"error": "forbidden"})

        latest_task = dict(tasks[0])
        latest_state = None
        try:
            latest_state = await container.orchestrator.get_state(
                latest_task["task_id"]
            )
        except Exception:  # noqa: BLE001 - 详情页允许状态缺失
            latest_state = None
        return {
            "session_id": session_id,
            "messages": await container.orchestrator.get_messages(session_id),
            "tasks": [dict(row) for row in tasks],
            "latest_task": latest_task,
            "latest_state": latest_state,
        }

    @router.get("/tasks/{task_id}/approvals")
    async def task_approvals(task_id: str, request: Request):
        ctx = build_context(request)
        task = await container.db.fetchone(
            "SELECT user_id FROM tasks WHERE task_id = ?", (task_id,)
        )
        if task is None:
            return JSONResponse(status_code=404, content={"error": "not found"})
        if not _is_admin(ctx) and task["user_id"] != ctx.user_id:
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        rows = await container.db.fetchall(
            "SELECT a.*, t.trace_id, t.user_id, t.tenant_id AS task_tenant_id, "
            "t.status AS task_status FROM approvals a "
            "LEFT JOIN tasks t ON t.task_id = a.task_id "
            "WHERE a.task_id = ? ORDER BY a.created_at DESC",
            (task_id,),
        )
        return {"approvals": [await _approval_item(row) for row in rows]}

    @router.get("/sessions")
    async def sessions(request: Request, limit: int = 50):
        # 会话来自 messages；任务状态通过 task_id 关联，供历史列表显示进展。
        ctx = build_context(request)
        rows = await container.db.fetchall(
            "SELECT m.session_id, COUNT(*) AS message_count, "
            "MAX(m.created_at) AS updated_at, "
            "(SELECT content FROM messages m2 WHERE m2.session_id = m.session_id "
            " ORDER BY m2.id DESC LIMIT 1) AS last_message, "
            "(SELECT role FROM messages m2 WHERE m2.session_id = m.session_id "
            " ORDER BY m2.id DESC LIMIT 1) AS last_role "
            "FROM messages m JOIN tasks t ON t.task_id = m.task_id "
            "WHERE t.user_id = ? GROUP BY m.session_id "
            "ORDER BY updated_at DESC LIMIT ?",
            (ctx.user_id, limit),
        )
        result = []
        for row in rows:
            item = dict(row)
            latest = await container.db.fetchone(
                "SELECT t.task_id, t.trace_id, t.status, t.revision, t.updated_at "
                "FROM tasks t JOIN messages m ON m.task_id = t.task_id "
                "WHERE m.session_id = ? ORDER BY t.updated_at DESC LIMIT 1",
                (item["session_id"],),
            )
            item["latest_task"] = dict(latest) if latest else None
            result.append(item)
        return {"sessions": result}

    @router.get("/sessions/{session_id}/messages")
    async def session_messages(session_id: str, limit: int = 100):
        return {
            "session_id": session_id,
            "messages": await container.orchestrator.get_messages(session_id, limit),
        }

    @router.get("/tasks/{task_id}/state")
    async def task_state(task_id: str):
        # 供聊天页在审批完成后重新加载待确认中断。
        return await container.orchestrator.get_state(task_id)

    @router.get("/tasks/{task_id}/history")
    async def task_history(task_id: str, limit: int = 100):
        # Checkpoint 历史用于“状态级回放”，和 trace 的调用树互补。
        return {
            "task_id": task_id,
            "history": await container.orchestrator.get_history(task_id, limit),
        }

    async def _approval_item(row) -> dict:
        """把审批行转成前端结构；旧数据从 Checkpoint 回填快照。"""
        item = dict(row)
        payload = json.loads(item["payload"]) if item["payload"] else None
        if payload is None and item.get("task_id"):
            try:
                state = await container.orchestrator.get_state(item["task_id"])
                values = state.get("values") or {}
                if values:
                    payload = {
                        "request": values.get("request"),
                        "options": values.get("options"),
                        "policy_result": values.get("policy_result"),
                        "revision": values.get("revision"),
                    }
            except Exception:  # noqa: BLE001 - 旧审批单允许缺失快照
                payload = None
        item["payload"] = payload
        item["tenant_id"] = item.pop("task_tenant_id", None)
        return item

    @router.get("/approvals")
    async def approvals(request: Request, status: str = "pending",
                        limit: int = 50):
        ctx = build_context(request)
        if not _is_admin(ctx):
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        rows = await container.db.fetchall(
            "SELECT a.*, t.trace_id, t.user_id, t.tenant_id AS task_tenant_id, "
            "t.status AS task_status FROM approvals a "
            "LEFT JOIN tasks t ON t.task_id = a.task_id "
            "WHERE a.status = ? ORDER BY a.created_at DESC LIMIT ?",
            (status, limit),
        )
        return {"approvals": [await _approval_item(row) for row in rows]}

    @router.get("/approvals/{approval_id}")
    async def approval_detail(approval_id: str, request: Request):
        ctx = build_context(request)
        if not _is_admin(ctx):
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        row = await container.db.fetchone(
            "SELECT a.*, t.trace_id, t.user_id, t.tenant_id AS task_tenant_id, "
            "t.status AS task_status FROM approvals a "
            "LEFT JOIN tasks t ON t.task_id = a.task_id WHERE a.approval_id = ?",
            (approval_id,),
        )
        if row is None:
            return JSONResponse(status_code=404, content={"error": "not found"})
        return await _approval_item(row)

    @router.post("/feedback")
    async def feedback(payload: FeedbackRequest, request: Request):
        # 反馈入口不做强鉴权，但必须脱敏；tenant 从 mock 上下文取。
        ctx = build_context(request)
        badcase_id = uuid4().hex
        now = datetime.now(UTC).isoformat()
        await container.db.execute(
            "INSERT INTO badcases (badcase_id, trace_id, task_id, tenant_id, "
            "category, severity, user_input, expected, actual, comment, status, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                badcase_id, payload.trace_id, payload.task_id, ctx.tenant_id,
                payload.category, payload.severity,
                scrub(payload.user_input), scrub(payload.expected),
                scrub(payload.actual), scrub(payload.comment),
                "open", now, now,
            ),
        )
        return {"badcase_id": badcase_id, "status": "open"}

    @router.get("/badcases")
    async def list_badcases(request: Request, status: str | None = None,
                            limit: int = 50):
        ctx = build_context(request)
        if not _is_admin(ctx):
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        if status:
            rows = await container.db.fetchall(
                "SELECT * FROM badcases WHERE status = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            rows = await container.db.fetchall(
                "SELECT * FROM badcases ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return {"badcases": [dict(row) for row in rows]}

    @router.patch("/badcases/{badcase_id}")
    async def update_badcase(badcase_id: str, payload: BadcaseUpdate,
                             request: Request):
        ctx = build_context(request)
        if not _is_admin(ctx):
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        row = await container.db.fetchone(
            "SELECT badcase_id FROM badcases WHERE badcase_id = ?",
            (badcase_id,),
        )
        if row is None:
            return JSONResponse(status_code=404, content={"error": "not found"})

        updates = payload.model_dump(exclude_none=True)
        if updates:
            assignments = ", ".join(f"{key} = ?" for key in updates)
            await container.db.execute(
                f"UPDATE badcases SET {assignments}, updated_at = ? "
                f"WHERE badcase_id = ?",
                (*updates.values(), datetime.now(UTC).isoformat(), badcase_id),
            )
        return {"ok": True}

    @router.post("/admin/approvals/{approval_id}/approve")
    async def approve(approval_id: str, payload: AdminDecision, request: Request):
        ctx = build_context(request)
        if not _is_admin(ctx):
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
        if not _is_admin(ctx):
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        row = await container.db.fetchone(
            "SELECT approval_id FROM approvals WHERE approval_id = ?",
            (approval_id,),
        )
        if row is None:
            return JSONResponse(status_code=404, content={"error": "not found"})
        await container.approvals.decide(approval_id, "rejected", payload.comment)
        return {"ok": True}

    @router.get("/traces")
    async def traces(limit: int = 50):
        return {"traces": await list_traces(container.db, limit)}

    @router.get("/traces/overview")
    async def traces_overview():
        # 固定路径必须放在 /traces/{trace_id} 之前。
        return await trace_overview(container.db)

    @router.get("/traces/{trace_id}/flow")
    async def trace_flow(trace_id: str):
        spans = await container.db.fetchall(
            "SELECT name, status, start_time FROM spans "
            "WHERE trace_id = ? AND layer = 'orchestration' "
            "ORDER BY start_time",
            (trace_id,),
        )
        task = await container.db.fetchone(
            "SELECT task_id, status FROM tasks WHERE trace_id = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (trace_id,),
        )
        flow = build_flow([dict(span) for span in spans])
        flow.update({
            "trace_id": trace_id,
            "task_id": task["task_id"] if task else None,
            "task_status": task["status"] if task else None,
        })
        return flow

    @router.get("/traces/{trace_id}")
    async def trace_json(trace_id: str):
        task = await container.db.fetchone(
            "SELECT task_id, status FROM tasks WHERE trace_id = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (trace_id,),
        )
        return {
            "trace_id": trace_id,
            "task_id": task["task_id"] if task else None,
            "task_status": task["status"] if task else None,
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
