"""Trace 查询用例（CQRS-lite）。

职责：
- 权限/租户检查在这里做，仓储只管取数；
- 组合 span 与任务索引，还原调用树和流转图；
- 输出前端可直接消费的 DTO，控制器不再拼字段。
"""

from itinerary_agent.application.access import (
    is_admin,
    require_scope,
    require_tenant_access,
)
from itinerary_agent.application.pagination import (
    build_page,
    decode_cursor,
    normalize_limit,
)
from itinerary_agent.application.ports import (
    TaskRepositoryPort,
    TraceRepositoryPort,
)
from itinerary_agent.domain.models import RequestContext
from itinerary_agent.observability.flow import build_flow
from itinerary_agent.observability.query import build_overview, build_trace_tree


class TraceQueryService:
    def __init__(self, trace_repo: TraceRepositoryPort,
                 task_repo: TaskRepositoryPort):
        self.trace_repo = trace_repo
        self.task_repo = task_repo

    def _visible_tenant(self, ctx: RequestContext) -> str | None:
        """管理员看全量；普通员工只看本租户。"""
        return None if is_admin(ctx) else ctx.tenant_id

    def _require_cluster_access(self, ctx: RequestContext,
                                task: dict | None) -> None:
        """trace 可能没绑定任务（后台/检索），有任务时按租户校验。"""
        if task is not None:
            require_tenant_access(ctx, task)

    async def list_traces(self, ctx: RequestContext, limit: int = 50,
                          cursor: str | None = None) -> dict:
        require_scope(ctx, "trace:read")
        page_size = normalize_limit(limit)
        rows = await self.trace_repo.list_traces(
            page_size,
            tenant_id=self._visible_tenant(ctx),
            cursor=decode_cursor(cursor),
        )
        traces, next_cursor = build_page(
            rows, page_size,
            lambda item: {
                "started_at": item["started_at"],
                "trace_id": item["trace_id"],
            },
        )
        return {"traces": traces, "next_cursor": next_cursor}

    async def list_task_summaries(self, ctx: RequestContext,
                                  limit: int = 50,
                                  cursor: str | None = None) -> dict:
        require_scope(ctx, "trace:read")
        page_size = normalize_limit(limit)
        rows = await self.trace_repo.list_task_summaries(
            page_size,
            tenant_id=self._visible_tenant(ctx),
            cursor=decode_cursor(cursor),
        )
        tasks, next_cursor = build_page(
            rows, page_size,
            lambda item: {
                "updated_at": item["updated_at"],
                "task_id": item["task_id"],
            },
        )
        return {"tasks": tasks, "next_cursor": next_cursor}

    async def list_task_traces(self, ctx: RequestContext, task_id: str) -> dict:
        require_scope(ctx, "trace:read")
        task = await self.task_repo.get(task_id)
        self._require_cluster_access(ctx, task)
        return {
            "task_id": task_id,
            "traces": await self.trace_repo.list_traces_for_task(task_id),
        }

    async def overview(self, ctx: RequestContext) -> dict:
        """线上概览。

        聚合指标目前是全局的；生产环境应按租户在分析存储里预聚合。
        """
        require_scope(ctx, "trace:read")
        snapshot = await self.trace_repo.overview_snapshot()
        recent = await self.trace_repo.list_traces(limit=10)
        return build_overview(snapshot, recent)

    async def get_trace(self, ctx: RequestContext, trace_id: str) -> dict:
        """Trace 回放详情：任务索引 + 调用树。"""
        require_scope(ctx, "trace:read")
        task = await self.task_repo.find_by_trace(trace_id)
        self._require_cluster_access(ctx, task)
        return {
            "trace_id": trace_id,
            "task_id": task["task_id"] if task else None,
            "task_status": task["status"] if task else None,
            "spans": build_trace_tree(await self.trace_repo.load_spans(trace_id)),
        }

    async def get_flow(self, ctx: RequestContext, trace_id: str) -> dict:
        """编排流转图：只取 orchestration 层 span 生成时间线。"""
        require_scope(ctx, "trace:read")
        task = await self.task_repo.find_by_trace(trace_id)
        self._require_cluster_access(ctx, task)
        flow = build_flow(await self.trace_repo.load_flow_spans(trace_id))
        flow.update({
            "trace_id": trace_id,
            "task_id": task["task_id"] if task else None,
            "task_status": task["status"] if task else None,
        })
        return flow
