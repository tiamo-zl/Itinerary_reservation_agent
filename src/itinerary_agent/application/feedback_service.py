"""反馈与 badcase 回流用例。

反馈写入不做强鉴权（员工顺手标记问题），但只允许管理员列表和推进状态。
"""

from datetime import UTC, datetime
from uuid import uuid4

from itinerary_agent.application.access import (
    require_admin,
    require_found,
    require_scope,
)
from itinerary_agent.application.pagination import (
    build_page,
    decode_cursor,
    normalize_limit,
)
from itinerary_agent.application.ports import FeedbackRepositoryPort
from itinerary_agent.domain.models import RequestContext


class FeedbackService:
    def __init__(self, feedback_repo: FeedbackRepositoryPort):
        self.feedback_repo = feedback_repo

    async def submit(self, ctx: RequestContext, feedback: dict) -> dict:
        """创建 badcase；文本已由网关脱敏，这里只补租户和时间。"""
        require_scope(ctx, "feedback:write")
        badcase_id = uuid4().hex
        now = datetime.now(UTC).isoformat()
        await self.feedback_repo.create({
            "badcase_id": badcase_id,
            "trace_id": feedback["trace_id"],
            "task_id": feedback.get("task_id"),
            "tenant_id": ctx.tenant_id,
            "category": feedback["category"],
            "severity": feedback["severity"],
            "user_input": feedback.get("user_input", ""),
            "expected": feedback.get("expected", ""),
            "actual": feedback.get("actual", ""),
            "comment": feedback.get("comment", ""),
            "status": "open",
            "created_at": now,
            "updated_at": now,
        })
        return {"badcase_id": badcase_id, "status": "open"}

    async def list_badcases(self, ctx: RequestContext,
                            status: str | None = None,
                            limit: int = 50,
                            cursor: str | None = None) -> dict:
        require_scope(ctx, "badcase:manage")
        require_admin(ctx)
        page_size = normalize_limit(limit)
        rows = await self.feedback_repo.list_badcases(
            status, page_size, decode_cursor(cursor)
        )
        rows, next_cursor = build_page(
            rows, page_size,
            lambda row: {
                "created_at": row["created_at"],
                "badcase_id": row["badcase_id"],
            },
        )
        return {"badcases": rows, "next_cursor": next_cursor}

    async def update(self, ctx: RequestContext, badcase_id: str,
                     changes: dict) -> dict:
        """推进 badcase 状态；只更新显式传入的字段。"""
        require_scope(ctx, "badcase:manage")
        require_admin(ctx)
        require_found(await self.feedback_repo.get(badcase_id), "badcase")
        if changes:
            await self.feedback_repo.update(badcase_id, changes)
        return {"ok": True}
