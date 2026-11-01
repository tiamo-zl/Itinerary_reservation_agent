"""会话/对话记录查询用例。

权限规则：
- 管理员（approver/admin）可看本租户全部会话；
- 普通员工只看自己的会话。
"""

from __future__ import annotations

from itinerary_agent.application.access import (
    is_admin,
    require_found,
    require_scope,
)
from itinerary_agent.application.errors import Forbidden
from itinerary_agent.application.pagination import (
    build_page,
    decode_cursor,
    normalize_limit,
)
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
                                  limit: int = 100,
                                  cursor: str | None = None) -> dict:
        require_scope(ctx, "conversation:read")
        page_size = normalize_limit(limit, default=100)
        rows = await self.conversation_repo.list_conversations(
            admin=is_admin(ctx),
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            limit=page_size,
            cursor=decode_cursor(cursor),
        )
        items, next_cursor = build_page(
            rows, page_size,
            lambda item: {
                "updated_at": item["updated_at"],
                "session_id": item["session_id"],
            },
        )
        return {"conversations": items, "next_cursor": next_cursor}

    async def list_sessions(self, ctx: RequestContext, limit: int = 50,
                            cursor: str | None = None) -> dict:
        require_scope(ctx, "conversation:read")
        page_size = normalize_limit(limit)
        rows = await self.conversation_repo.list_sessions(
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            limit=page_size,
            cursor=decode_cursor(cursor),
        )
        items, next_cursor = build_page(
            rows, page_size,
            lambda item: {
                "updated_at": item["updated_at"],
                "session_id": item["session_id"],
            },
        )
        return {"sessions": items, "next_cursor": next_cursor}

    async def detail(self, ctx: RequestContext, session_id: str) -> dict:
        """会话详情：任务、消息和最新任务的当前进展。

        步骤：
        1. 取会话下的全部任务；
        2. 无任务视为会话不存在，避免泄露空会话；
        3. 校验租户与归属（管理员除外）；
        4. 取最新任务的 Checkpoint 当前状态，缺失时允许为 None；
        5. 组合消息与任务列表返回。
        """
        require_scope(ctx, "conversation:read")
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

    async def messages(self, ctx: RequestContext, session_id: str,
                       limit: int = 100) -> list[dict]:
        """会话消息；员工只能读自己参与过的会话。

        Trace/流转图按 trace 反查会话后也走这里，因此归属校验必须
        放在应用服务，而不是依赖前端页面。
        """
        require_scope(ctx, "conversation:read")
        tasks = await self.conversation_repo.list_tasks(session_id)
        require_found(tasks, "session")
        if not is_admin(ctx) and any(
            task["tenant_id"] != ctx.tenant_id
            or task["user_id"] != ctx.user_id
            for task in tasks
        ):
            raise Forbidden("forbidden")
        return await self.orchestration.get_messages(session_id, limit)
