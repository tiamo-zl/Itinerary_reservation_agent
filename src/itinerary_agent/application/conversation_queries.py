"""会话/对话记录查询用例。

权限规则：
- 管理员（approver/admin）可看本租户全部会话；
- 普通员工只看自己的会话。
"""

from __future__ import annotations

from itinerary_agent.application.access import is_admin, require_found
from itinerary_agent.application.errors import Forbidden
from itinerary_agent.application.ports import (
    ConversationRepositoryPort,
    OrchestrationPort,
)
from itinerary_agent.domain.models import RequestContext


class ConversationQueryService:
    def __init__(self, conversation_repo: ConversationRepositoryPort,
                 orchestration: OrchestrationPort):
        self.conversation_repo = conversation_repo
        self.orchestration = orchestration

    async def list_conversations(self, ctx: RequestContext,
                                  limit: int = 100) -> dict:
        return {
            "conversations": await self.conversation_repo.list_conversations(
                admin=is_admin(ctx),
                user_id=ctx.user_id,
                tenant_id=ctx.tenant_id,
                limit=limit,
            )
        }

    async def list_sessions(self, ctx: RequestContext, limit: int = 50) -> dict:
        return {
            "sessions": await self.conversation_repo.list_sessions(
                user_id=ctx.user_id,
                tenant_id=ctx.tenant_id,
                limit=limit,
            )
        }

    async def detail(self, ctx: RequestContext, session_id: str) -> dict:
        """会话详情：任务、消息和最新任务的当前进展。

        步骤：
        1. 取会话下的全部任务；
        2. 无任务视为会话不存在，避免泄露空会话；
        3. 校验租户与归属（管理员除外）；
        4. 取最新任务的 Checkpoint 当前状态，缺失时允许为 None；
        5. 组合消息与任务列表返回。
        """
        # 步骤 1-2：会话必须至少有一个任务。
        tasks = await self.conversation_repo.list_tasks(session_id)
        require_found(tasks, "session")

        # 步骤 3：普通员工只能读本租户、自己的会话。
        if not is_admin(ctx) and (
            any(task["tenant_id"] != ctx.tenant_id for task in tasks)
            or all(task["user_id"] != ctx.user_id for task in tasks)
        ):
            raise Forbidden("forbidden")

        # 步骤 4：最新任务的当前进展；历史数据缺失 Checkpoint 时不失败。
        latest_task = tasks[0]
        try:
            latest_state = await self.orchestration.get_state(
                latest_task["task_id"]
            )
        except Exception:  # noqa: BLE001 - 详情页允许状态缺失
            latest_state = None

        # 步骤 5：返回前端需要的完整结构。
        return {
            "session_id": session_id,
            "messages": await self.orchestration.get_messages(session_id),
            "tasks": tasks,
            "latest_task": latest_task,
            "latest_state": latest_state,
        }

    async def messages(self, session_id: str, limit: int = 100) -> list[dict]:
        """会话消息；Trace/流转图会按 trace 反查会话后再读取。

        这里保持只读且无副作用，归属校验由调用方页面决定；
        生产接入真实鉴权后应改为按 ctx 校验。
        """
        return await self.orchestration.get_messages(session_id, limit)
