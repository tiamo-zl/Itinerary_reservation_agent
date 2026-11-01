"""审批待办查询与管理员决策用例。

审批单读取走仓储；状态流转走外部审批系统（ApprovalSystemPort），
应用服务只负责权限、存在性校验和前端 DTO 组合。
"""

import json

from itinerary_agent.application.access import (
    require_admin,
    require_found,
    require_scope,
    require_task_access,
)
from itinerary_agent.application.pagination import (
    build_page,
    decode_cursor,
    normalize_limit,
)
from itinerary_agent.application.ports import (
    ApprovalRepositoryPort,
    ApprovalSystemPort,
    OrchestrationPort,
    OutboxRepositoryPort,
    TaskRepositoryPort,
    UnitOfWorkPort,
)
from itinerary_agent.domain.models import RequestContext


class ApprovalQueryService:
    def __init__(self, approval_repo: ApprovalRepositoryPort,
                 task_repo: TaskRepositoryPort,
                 orchestration: OrchestrationPort,
                 approval_system: ApprovalSystemPort,
                 outbox: OutboxRepositoryPort,
                 unit_of_work: UnitOfWorkPort,
                 audit=None):
        self.approval_repo = approval_repo
        self.task_repo = task_repo
        self.orchestration = orchestration
        self.approval_system = approval_system
        self.outbox = outbox
        self.unit_of_work = unit_of_work
        self.audit = audit

    async def list_approvals(self, ctx: RequestContext,
                             status: str = "pending",
                             limit: int = 50,
                             cursor: str | None = None) -> dict:
        require_scope(ctx, "approval:read")
        require_admin(ctx)
        page_size = normalize_limit(limit)
        rows = await self.approval_repo.list_by_status(
            status, page_size, decode_cursor(cursor)
        )
        rows, next_cursor = build_page(
            rows, page_size,
            lambda row: {
                "created_at": row["created_at"],
                "approval_id": row["approval_id"],
            },
        )
        return {
            "approvals": [await self._to_item(row) for row in rows],
            "next_cursor": next_cursor,
        }

    async def get(self, ctx: RequestContext, approval_id: str) -> dict:
        require_scope(ctx, "approval:read")
        require_admin(ctx)
        row = require_found(
            await self.approval_repo.get(approval_id), "approval"
        )
        return await self._to_item(row)

    async def list_for_task(self, ctx: RequestContext, task_id: str) -> dict:
        """任务关联的审批单；员工本人和审批人都能看。"""
        require_scope(ctx, "task:read")
        task = require_found(await self.task_repo.get(task_id), "task")
        require_task_access(ctx, task)
        rows = await self.approval_repo.list_for_task(task_id)
        return {"approvals": [await self._to_item(row) for row in rows]}

    async def decide(self, ctx: RequestContext, approval_id: str,
                     decision: str, comment: str) -> dict:
        """管理员通过/驳回。

        步骤：
        1. 校验管理员权限和审批单存在；
        2. 读取任务归属，供 worker 构造恢复上下文；
        3. 同一事务内更新审批状态并写 outbox 事件；
        4. worker 异步领取事件并从 Checkpoint 恢复任务。
        """
        require_scope(ctx, "approval:decide")
        require_admin(ctx)
        approval = require_found(
            await self.approval_repo.get(approval_id), "approval"
        )
        task = require_found(
            await self.task_repo.get(approval["task_id"]), "task"
        )

        async with self.unit_of_work.transaction():
            await self.approval_system.decide(approval_id, decision, comment)
            if self.audit is not None:
                # 审批决定与 outbox 同事务；审计失败不吞掉决定本身，
                # 但同一事务回滚可以保证不会出现“已决定、无审计”。
                await self.audit.record(
                    ctx.trace_id, task["task_id"], ctx.user_id,
                    "approval.decide",
                    {"approval_id": approval_id, "status": decision,
                     "comment": comment},
                    [], "", decision, comment or "approval decision",
                )
            await self.outbox.enqueue(
                aggregate_type="approval",
                aggregate_id=approval_id,
                event_type="approval.decided",
                payload={
                    "approval_id": approval_id,
                    "task_id": task["task_id"],
                    "status": decision,
                    "comment": comment,
                    "trace_id": task.get("trace_id"),
                },
            )
        return {"ok": True}

    async def _to_item(self, row: dict) -> dict:
        """把审批行转成前端结构；旧数据从 Checkpoint 回填快照。"""
        item = dict(row)
        item["payload"] = await self._payload(item)
        item["tenant_id"] = item.pop("task_tenant_id", None)
        return item

    async def _payload(self, item: dict) -> dict | None:
        """优先用提交时落库的快照；历史审批单从任务状态回填。"""
        if item.get("payload"):
            return json.loads(item["payload"])
        if not item.get("task_id"):
            return None
        try:
            state = await self.orchestration.get_state(item["task_id"])
        except Exception:  # noqa: BLE001 - 旧审批单允许缺失快照
            return None
        values = state.get("values") or {}
        if not values:
            return None
        return {
            "request": values.get("request"),
            "options": values.get("options"),
            "policy_result": values.get("policy_result"),
            "revision": values.get("revision"),
        }
