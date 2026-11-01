"""任务查询用例。

任务索引在 tasks 表，完整状态在 LangGraph Checkpoint；
两个来源都在这里组合，控制器只拿结果。
"""

from itinerary_agent.application.access import require_found, require_tenant_access
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

    async def get(self, ctx: RequestContext, task_id: str) -> dict:
        task = require_found(await self.task_repo.get(task_id), "task")
        require_tenant_access(ctx, task)
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
