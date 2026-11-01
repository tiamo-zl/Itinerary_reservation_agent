"""任务查询用例。

任务索引在 tasks 表，完整状态在 LangGraph Checkpoint；
两个来源都在这里组合，控制器只拿结果。
"""

from itinerary_agent.application.access import (
    require_found,
    require_scope,
    require_task_access,
)
from itinerary_agent.application.ports import OrchestrationPort, TaskRepositoryPort
from itinerary_agent.domain.models import RequestContext


class TaskQueryService:
    def __init__(self, task_repo: TaskRepositoryPort,
                 orchestration: OrchestrationPort):
        self.task_repo = task_repo
        self.orchestration = orchestration

    async def get_trace_id(self, task_id: str) -> str | None:
        """恢复接口复用任务首次请求的 trace，不作为用户可见数据。"""
        return await self.task_repo.get_trace_id(task_id)

    async def authorize_resume(self, ctx: RequestContext,
                               task_id: str) -> str | None:
        """恢复任务前确认归属；返回任务 trace 供 SSE 复用。"""
        require_scope(ctx, "chat")
        task = require_found(await self.task_repo.get(task_id), "task")
        require_task_access(ctx, task)
        return task.get("trace_id") or await self.task_repo.get_trace_id(
            task_id
        )

    async def get(self, ctx: RequestContext, task_id: str) -> dict:
        require_scope(ctx, "task:read")
        task = require_found(await self.task_repo.get(task_id), "task")
        # 任务详情属于个人数据：员工只能看自己的，管理员可跨用户。
        require_task_access(ctx, task)
        return task

    async def get_state(self, ctx: RequestContext, task_id: str) -> dict:
        """当前 Checkpoint 状态，供聊天页恢复中断/刷新使用。"""
        await self.get(ctx, task_id)
        return await self.orchestration.get_state(task_id)

    async def get_history(self, ctx: RequestContext, task_id: str,
                          limit: int = 100) -> list[dict]:
        """Checkpoint 历史，用于状态级回放。"""
        await self.get(ctx, task_id)
        return await self.orchestration.get_history(task_id, limit)
