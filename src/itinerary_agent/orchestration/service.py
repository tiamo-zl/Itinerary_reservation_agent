"""编排服务：对网关暴露极小的开始/恢复接口。

网关不需要知道 LangGraph 的存在；图、Checkpoint、节点路由都封装在这里。
M1 只实现 start_turn，M2 增加 interrupt/resume，M4 增加审批与下单。
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import uuid4

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

logger = logging.getLogger(__name__)


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
                 checkpointer=None, memory=None, rules=None,
                 audit=None, task_repo=None, lease_seconds: int = 300):
        from langgraph.checkpoint.memory import MemorySaver

        self.model = model
        self.traces = traces
        self.tools = tools
        self.knowledge = knowledge
        self.control = control
        self.memory = memory
        self.rules = rules
        self.audit = audit
        # 任务租约仓储；测试可注入 fake 或省略。
        self.task_repo = task_repo
        self.lease_seconds = lease_seconds
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
        """从图状态重建网关上下文。

        角色/scope 在 start_turn 时固化进 Checkpoint；旧 Checkpoint
        没有这两个字段时按最低业务角色（employee）处理。
        """
        roles = list(state.get("roles") or ["employee"])
        return RequestContext(
            trace_id=state["trace_id"], tenant_id=state["tenant_id"],
            user_id=state["user_id"], session_id=state["session_id"],
            roles=roles, scopes=list(state.get("scopes") or []),
        )

    async def _upsert_task(self, state: dict, status: str) -> None:
        """把任务索引写入仓储；完整状态仍由 Checkpoint 保存。"""
        if self.task_repo is None:
            return
        await self.task_repo.upsert(
            state["task_id"], state["tenant_id"], state["user_id"],
            status, state["revision"], state.get("trace_id"),
        )

    async def _set_task_status(self, task_id: str, status: str) -> None:
        if self.task_repo is None:
            return
        await self.task_repo.set_status(task_id, status)

    async def guarded_invoke(self, state: dict, action: str, name: str,
                             args: dict) -> ToolResult:
        """在编排层统一做动作准入，再交给工具层执行。

        guard 放在这里而不是 ToolService，避免工具层反向依赖控制层。
        所有拒绝和高风险写操作都落审计；审计失败只记日志，不改变业务结果。
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
                await self._audit(
                    state, action, args, "denied",
                    f"{guard.code}: {guard.message}",
                )
                return ToolResult(
                    ok=False, trace_id=state["trace_id"],
                    error=ToolError(code=guard.code, message=guard.message),
                )

        tool_result = await self.tools.invoke(self.ctx_of(state), name, args)
        if action.startswith("book_") or action == "submit_approval":
            replayed = bool(
                tool_result.ok
                and (tool_result.data or {}).get("replayed")
            )
            decision = (
                "replayed" if replayed
                else "allowed" if tool_result.ok
                else "failed"
            )
            reason = (
                "idempotent replay" if replayed
                else "tool success" if tool_result.ok
                else (tool_result.error.code if tool_result.error else "failed")
            )
            await self._audit(state, action, args, decision, reason)
        return tool_result

    async def _audit(self, state: dict, action: str, inputs: dict,
                     decision: str, reason: str) -> None:
        """写审计；审计不可用时降级为日志，不能阻断主流程。"""
        if self.audit is None:
            return
        try:
            await self.audit.record(
                state["trace_id"], state["task_id"], state["user_id"],
                action, inputs, list(state.get("policy_refs") or []),
                getattr(self.rules, "version", "") if self.rules else "",
                decision, reason,
            )
        except Exception:
            logger.exception("audit write failed: %s", action)

    async def get_user_profile(self, state: dict) -> UserProfile:
        result = await self.tools.invoke(self.ctx_of(state), "get_user_profile", {})
        return UserProfile.model_validate(result.data)

    async def start_turn(self, ctx: RequestContext, message: str) -> AsyncIterator[Event]:
        """开始一轮对话并流式产出事件。

        步骤：
        1. 初始化任务状态、trace/task 上下文；
        2. 记录用户消息和任务索引；
        3. 流式执行图，逐节点产出 progress；
        4. interrupt 时落状态并产出 interrupt 事件；
        5. 结束后更新最终状态、记录助手摘要并产出 result。
        """
        # 步骤 1：初始化状态并绑定 trace/task 上下文。
        state = initial_state(ctx, message)
        config = {"configurable": {"thread_id": state["task_id"]}}
        if self.traces is not None:
            self.traces.start_trace(state["trace_id"])
            self.traces.set_task(state["task_id"])

        # 步骤 2：持久化用户消息和任务索引。
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

        # 步骤 3/4：流式执行图，区分 progress 和 interrupt。
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

        # 步骤 5：落最终状态/摘要，返回 result。
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
        """带租约的恢复入口。

        用户点击恢复与 worker 处理 outbox 可能同时发生；只有拿到租约的
        调用者能执行，另一个收到 TASK_BUSY 错误事件。
        """
        owner = f"resume-{uuid4().hex[:12]}"
        if self.task_repo is not None:
            leased = await self.task_repo.acquire_resume_lease(
                task_id, owner, self.lease_seconds
            )
            if leased is None:
                yield Event(type="error", data={
                    "task_id": task_id,
                    "trace_id": ctx.trace_id,
                    "code": "TASK_BUSY",
                    "message": "任务正在被其他进程恢复或已结束。",
                })
                return
        try:
            async for event in self._resume_locked(ctx, task_id, decision):
                yield event
        finally:
            if self.task_repo is not None:
                await self.task_repo.release_lease(task_id, owner)

    async def _resume_locked(self, ctx: RequestContext, task_id: str,
                             decision: Decision) -> AsyncIterator[Event]:
        """从 Checkpoint 恢复被 interrupt 的任务（调用方必须持有租约）。

        步骤：
        1. 绑定任务 trace/task 上下文；
        2. 处理 pause/cancel 两个终止类动作；
        3. 处理 modify：更新需求/revision 后重新规划；
        4. 普通恢复前确认 Checkpoint 现场存在；
        5. 构造审批或确认恢复 payload；
        6. 流式恢复图并产出 progress/interrupt；
        7. 更新最终状态、记录摘要并产出 result。
        """
        from langgraph.types import Command

        # 步骤 1：恢复必须沿用任务 trace，避免孤立 trace。
        config = {"configurable": {"thread_id": task_id}}
        if self.traces is not None:
            self.traces.start_trace(ctx.trace_id)
            self.traces.set_task(task_id)

        # 步骤 2：pause/cancel 不恢复图，直接写终态。
        if decision.action == "pause":
            # 暂停不销毁现场；后续 continue 仍从同一个 interrupt 恢复。
            await self._set_task_status(task_id, "PAUSED")
            yield Event(type="result", data={"task_id": task_id, "trace_id": ctx.trace_id, "status": "PAUSED"})
            return
        if decision.action == "cancel":
            await self._set_task_status(task_id, "CANCELLED")
            yield Event(type="result", data={"task_id": task_id, "trace_id": ctx.trace_id, "status": "CANCELLED"})
            return

        # 步骤 3：修改需求时先更新 Checkpoint，再让 confirm 重新路由。
        if decision.action == "modify" and decision.amended_request is not None:
            # 校验现场可见后，清空旧选项/旧审批/旧确认，并 revision++。
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

            # 修改后的图会重新 plan → search → policy，可能再次 interrupt。
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

        # 步骤 4：Checkpoint 刚写完时短时间内可能不可见，先确认现场存在。
        snapshot = await self._await_interrupted_state(config)
        if not snapshot.values or not snapshot.next:
            yield Event(type="error", data={
                "task_id": task_id, "trace_id": ctx.trace_id,
                "code": "CHECKPOINT_NOT_READY",
                "message": "任务现场尚未就绪或已结束，无法恢复。",
            })
            return

        # 步骤 5：审批恢复只传 status/comment；确认/修改传完整 Decision。
        payload = decision.model_dump()
        if decision.approval_status is not None:
            payload = {
                "status": decision.approval_status.value,
                "comment": decision.comment or "",
            }

        # 步骤 6：从 interrupt 现场继续流式执行。
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

        # 步骤 7：落最终状态/摘要，返回 result。
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
