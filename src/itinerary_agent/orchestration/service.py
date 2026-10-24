"""编排服务：对网关暴露极小的开始/恢复接口。

网关不需要知道 LangGraph 的存在；图、Checkpoint、节点路由都封装在这里。
M1 只实现 start_turn，M2 增加 interrupt/resume，M4 增加审批与下单。
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from itinerary_agent.domain.models import (
    Decision,
    Event,
    ModelTier,
    RequestContext,
    TaskSnapshot,
    TaskStatus,
    ToolError,
    ToolResult,
    TripRequest,
    UserProfile,
)
from itinerary_agent.orchestration.graph import build_graph
from itinerary_agent.orchestration.state import initial_state


def apply_amendment(state: dict, request: TripRequest) -> dict:
    """应用需求修改：revision++，清空所有下游派生结果。

    这一步必须在恢复图之前做，确保旧选项/旧审批/旧确认不会复活。
    """
    return {
        **state,
        "request": request.model_dump(mode="json"),
        "revision": state["revision"] + 1,
        "options": {"flights": [], "hotels": []},
        "policy_result": None,
        "policy_refs": [],
        "approval": None,
        "selected": {},
        "confirmed": False,
        "pending_amendment": None,
        "pending_human": None,
        "error": None,
        "status": "PLANNING",
    }


class _NoopSpan:
    """没有 TraceRecorder 时的空 span，保证测试可以只注入模型。"""

    async def __aenter__(self):
        return None

    async def __aexit__(self, *args):
        return False


class OrchestrationService:
    def __init__(self, model, traces, tools, knowledge, control,
                 checkpointer=None, db=None, memory=None, rules=None, audit=None):
        from langgraph.checkpoint.memory import MemorySaver

        self.model = model
        self.traces = traces
        self.tools = tools
        self.knowledge = knowledge
        self.control = control
        self.db = db
        self.memory = memory
        self.rules = rules
        self.audit = audit
        # M1 使用内存 Checkpoint；M2 会由容器注入 AsyncSqliteSaver。
        self.checkpointer = checkpointer or MemorySaver()
        self.tier_light = ModelTier.LIGHT
        self.tier_standard = ModelTier.STANDARD
        self.tier_reasoning = ModelTier.REASONING
        self.graph = build_graph(self)

    def span(self, name: str, layer: str, trace_id: str | None = None, **attrs):
        if self.traces is None:
            return _NoopSpan()
        if trace_id:
            # 显式绑定 trace，避免审批轮询等无 gateway 上下文的恢复路径
            # 在独立 asyncio task 中丢失 contextvar 后生成新 trace。
            self.traces.start_trace(trace_id)
        return self.traces.span(name, layer, **attrs)

    def ctx_of(self, state: dict) -> RequestContext:
        """从图状态重建网关上下文；角色权限在 M2 由真实用户档案补齐。"""
        return RequestContext(
            trace_id=state["trace_id"], tenant_id=state["tenant_id"],
            user_id=state["user_id"], session_id=state["session_id"], roles=[],
        )

    async def _upsert_task(self, state: dict, status: str) -> None:
        """把任务索引写入 SQLite；完整状态仍由 Checkpoint 保存。"""
        if self.db is None:
            return
        await self.db.execute(
            "INSERT INTO tasks (task_id, tenant_id, user_id, status, revision, "
            "trace_id, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(task_id) DO UPDATE SET "
            "status=excluded.status, revision=excluded.revision, "
            "trace_id=excluded.trace_id, updated_at=excluded.updated_at",
            (state["task_id"], state["tenant_id"], state["user_id"], status,
             state["revision"], state.get("trace_id"),
             datetime.now(UTC).isoformat()),
        )

    async def _set_task_status(self, task_id: str, status: str) -> None:
        if self.db is None:
            return
        await self.db.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
            (status, datetime.now(UTC).isoformat(), task_id),
        )

    async def guarded_invoke(self, state: dict, action: str, name: str,
                             args: dict) -> ToolResult:
        """在编排层统一做动作准入，再交给工具层执行。

        guard 放在这里而不是 ToolService，避免工具层反向依赖控制层。
        """
        if self.control is not None:
            result = state.get("policy_result") or {}
            approval = state.get("approval") or {}
            snapshot = TaskSnapshot(
                task_id=state["task_id"],
                status=TaskStatus(state["status"]),
                revision=state["revision"],
                policy_passed=result.get("passed"),
                requires_approval=result.get("requires_approval", False),
                approval_status=approval.get("status"),
                confirmed=state.get("confirmed", False),
            )
            guard = self.control.guard(self.ctx_of(state), action, snapshot)
            if not guard.allowed:
                return ToolResult(
                    ok=False, trace_id=state["trace_id"],
                    error=ToolError(code=guard.code, message=guard.message),
                )
        return await self.tools.invoke(self.ctx_of(state), name, args)

    async def get_user_profile(self, state: dict) -> UserProfile:
        result = await self.tools.invoke(self.ctx_of(state), "get_user_profile", {})
        return UserProfile.model_validate(result.data)

    async def start_turn(self, ctx: RequestContext, message: str) -> AsyncIterator[Event]:
        """开始一轮对话并流式产出事件。

        astream(stream_mode="updates") 每个节点完成时产出一项；
        interrupt 会以 "__interrupt__" 键出现，M2 再转换成等待用户的 SSE。
        """
        state = initial_state(ctx, message)
        config = {"configurable": {"thread_id": state["task_id"]}}
        if self.memory is not None:
            await self.memory.append_message(
                ctx.session_id, state["task_id"], "user", message
            )
        await self._upsert_task(state, "PLANNING")
        yield Event(type="status", data={
            "task_id": state["task_id"],
            "trace_id": state["trace_id"],
            "status": "PLANNING",
        })

        interrupted_status: str | None = None
        async for update in self.graph.astream(state, config=config, stream_mode="updates"):
            for node, value in update.items():
                if node == "__interrupt__":
                    interrupt_value = value[0].value
                    interrupted_status = (
                        "WAITING_APPROVAL"
                        if interrupt_value.get("kind") == "approval"
                        else "WAITING_HUMAN"
                    )
                    await self._set_task_status(state["task_id"], interrupted_status)
                    yield Event(
                        type="interrupt",
                        data={"task_id": state["task_id"], "human_request": interrupt_value},
                    )
                else:
                    yield Event(
                        type="progress",
                        data={"task_id": state["task_id"], "node": node},
                    )

        final = await self.graph.aget_state(config)
        final_status = interrupted_status or final.values["status"]
        if interrupted_status is None:
            await self._upsert_task(state, final_status)
        summary = final.values.get("summary", "")
        if self.memory is not None and summary:
            await self.memory.append_message(
                ctx.session_id, state["task_id"], "assistant", summary
            )
        yield Event(
            type="result",
            data={
                "task_id": state["task_id"],
                "trace_id": state["trace_id"],
                "status": final_status,
                "summary": summary,
            },
        )

    async def get_messages(self, session_id: str, limit: int = 100) -> list[dict]:
        if self.memory is None:
            return []
        return await self.memory.list_messages(session_id, limit)

    async def get_state(self, task_id: str) -> dict:
        """返回任务当前 Checkpoint 状态，供聊天页恢复中断/刷新使用。"""
        config = {"configurable": {"thread_id": task_id}}
        snapshot = await self._await_interrupted_state(config)
        return {
            "values": dict(snapshot.values),
            "next": list(snapshot.next),
        }

    async def _await_interrupted_state(self, config):
        """等待 interrupt 现场可见。

        SQLite Checkpoint 与业务表共用连接时，SSE 刚结束的极短时间内
        aget_state 可能读到旧快照；resume 前短暂重试，避免误判为空任务。
        """
        snapshot = await self.graph.aget_state(config)
        for _ in range(40):
            if snapshot.values and snapshot.next:
                return snapshot
            await asyncio.sleep(0.05)
            snapshot = await self.graph.aget_state(config)
        return snapshot

    async def get_history(self, task_id: str, limit: int = 100) -> list[dict]:
        """读取 Checkpoint 历史，用于前端回放状态迁移。

        历史按 LangGraph 返回顺序（最新在前）；只暴露状态摘要，
        不额外读取制度原文或聊天全文。
        """
        config = {"configurable": {"thread_id": task_id}}
        history: list[dict] = []
        async for snapshot in self.graph.aget_state_history(config, limit=limit):
            created_at = getattr(snapshot, "created_at", None)
            if hasattr(created_at, "isoformat"):
                created_at = created_at.isoformat()
            history.append({
                "values": dict(snapshot.values),
                "next": list(snapshot.next),
                "created_at": created_at,
                "metadata": dict(snapshot.metadata or {}),
                "checkpoint_id": (
                    snapshot.config.get("configurable", {}).get("checkpoint_id")
                    if getattr(snapshot, "config", None) else None
                ),
            })
        return history

    async def resume(self, ctx: RequestContext, task_id: str,
                     decision: Decision) -> AsyncIterator[Event]:
        """从 Checkpoint 恢复被 interrupt 的任务。

        M2 只处理确认/取消；M3 增加修改请求，M4 增加审批结果。
        """
        from langgraph.types import Command

        config = {"configurable": {"thread_id": task_id}}
        if decision.action == "pause":
            # 暂停不销毁现场；后续 continue 仍从同一个 interrupt 恢复。
            await self._set_task_status(task_id, "PAUSED")
            yield Event(type="result", data={"task_id": task_id, "trace_id": ctx.trace_id, "status": "PAUSED"})
            return
        if decision.action == "cancel":
            await self._set_task_status(task_id, "CANCELLED")
            yield Event(type="result", data={"task_id": task_id, "trace_id": ctx.trace_id, "status": "CANCELLED"})
            return

        if decision.action == "modify" and decision.amended_request is not None:
            # 先更新 Checkpoint 中的需求与 revision，再恢复 confirm 节点。
            snapshot = await self._await_interrupted_state(config)
            if not snapshot.values or not snapshot.next:
                yield Event(type="error", data={
                    "task_id": task_id, "trace_id": ctx.trace_id,
                    "code": "CHECKPOINT_NOT_READY",
                    "message": "任务现场尚未就绪或已结束，无法修改。",
                })
                return
            amended = apply_amendment(snapshot.values, decision.amended_request)
            await self.graph.aupdate_state(config, amended)

            yield Event(type="status", data={"task_id": task_id, "trace_id": ctx.trace_id, "status": "PLANNING"})
            interrupted_status: str | None = None
            async for update in self.graph.astream(
                Command(resume={"action": "modify"}),
                config=config,
                stream_mode="updates",
            ):
                for node, value in update.items():
                    if node == "__interrupt__":
                        interrupt_value = value[0].value
                        interrupted_status = (
                            "WAITING_APPROVAL"
                            if interrupt_value.get("kind") == "approval"
                            else "WAITING_HUMAN"
                        )
                        await self._set_task_status(task_id, interrupted_status)
                        yield Event(
                            type="interrupt",
                            data={"task_id": task_id, "trace_id": ctx.trace_id,
                                  "human_request": interrupt_value},
                        )
                    else:
                        yield Event(
                            type="progress",
                            data={"task_id": task_id, "trace_id": ctx.trace_id, "node": node},
                        )
            final = await self.graph.aget_state(config)
            final_status = interrupted_status or final.values["status"]
            # 修改会改变 revision；即使再次停在确认节点也要更新任务索引。
            await self._upsert_task(final.values, final_status)
            if self.memory is not None and final.values.get("summary"):
                await self.memory.append_message(
                    final.values["session_id"], task_id, "assistant",
                    final.values["summary"],
                )
            yield Event(
                type="result", data={"task_id": task_id, "trace_id": ctx.trace_id, "status": final_status}
            )
            return

        # Checkpoint 刚写完时极短时间内可能不可见；先确认现场存在，
        # 避免 Command 从空状态重新跑 understand。
        snapshot = await self._await_interrupted_state(config)
        if not snapshot.values or not snapshot.next:
            yield Event(type="error", data={
                "task_id": task_id, "trace_id": ctx.trace_id,
                "code": "CHECKPOINT_NOT_READY",
                "message": "任务现场尚未就绪或已结束，无法恢复。",
            })
            return

        payload = decision.model_dump()
        if decision.approval_status is not None:
            # 审批轮询只传 approval_status；节点需要的是简单 status 字段。
            payload = {
                "status": decision.approval_status.value,
                "comment": decision.comment or "",
            }

        yield Event(type="status", data={"task_id": task_id, "trace_id": ctx.trace_id, "status": "EXECUTING"})
        interrupted_status: str | None = None
        async for update in self.graph.astream(
            Command(resume=payload), config=config, stream_mode="updates"
        ):
            for node, value in update.items():
                if node == "__interrupt__":
                    interrupt_value = value[0].value
                    interrupted_status = (
                        "WAITING_APPROVAL"
                        if interrupt_value.get("kind") == "approval"
                        else "WAITING_HUMAN"
                    )
                    await self._set_task_status(task_id, interrupted_status)
                    yield Event(
                        type="interrupt",
                        data={"task_id": task_id, "human_request": interrupt_value},
                    )
                else:
                    yield Event(
                        type="progress",
                        data={"task_id": task_id, "trace_id": ctx.trace_id, "node": node},
                    )

        final = await self.graph.aget_state(config)
        final_status = interrupted_status or final.values["status"]
        if interrupted_status is None:
            await self._upsert_task(final.values, final_status)
        if self.memory is not None and final.values.get("summary"):
            await self.memory.append_message(
                final.values["session_id"], task_id, "assistant",
                final.values["summary"],
            )
        yield Event(type="result", data={"task_id": task_id, "trace_id": ctx.trace_id, "status": final_status})
