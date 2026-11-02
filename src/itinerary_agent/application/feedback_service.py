"""反馈与 badcase 回流用例。

反馈写入不做强鉴权（员工顺手标记问题），但只允许管理员列表和推进状态。
"""

import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from itinerary_agent.application.access import (
    require_admin,
    require_found,
    require_scope,
)
from itinerary_agent.application.errors import BadRequest
from itinerary_agent.application.pagination import (
    build_page,
    decode_cursor,
    normalize_limit,
)
from itinerary_agent.application.ports import (
    FeedbackRepositoryPort,
    TicketPort,
)
from itinerary_agent.domain.models import RequestContext

logger = logging.getLogger(__name__)

SLA_DAYS = {"high": 1, "medium": 7, "low": 14}


class FeedbackService:
    def __init__(self, feedback_repo: FeedbackRepositoryPort,
                 ticket_port: TicketPort | None = None):
        self.feedback_repo = feedback_repo
        self.ticket_port = ticket_port

    async def submit(self, ctx: RequestContext, feedback: dict) -> dict:
        """创建 badcase 并生成工单；文本已由网关脱敏。"""
        require_scope(ctx, "feedback:write")
        badcase_id = uuid4().hex
        now = datetime.now(UTC)
        severity = feedback["severity"]
        record = {
            "badcase_id": badcase_id,
            "trace_id": feedback["trace_id"],
            "task_id": feedback.get("task_id"),
            "tenant_id": ctx.tenant_id,
            "category": feedback["category"],
            "severity": severity,
            "user_input": feedback.get("user_input", ""),
            "expected": feedback.get("expected", ""),
            "actual": feedback.get("actual", ""),
            "comment": feedback.get("comment", ""),
            "status": "open",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "owner": None,
            "sla_due_at": (
                now + timedelta(days=SLA_DAYS.get(severity, 7))
            ).isoformat(),
            "ticket_ref": None,
        }
        if self.ticket_port is not None:
            record["ticket_ref"] = await self.ticket_port.create(record)
        await self.feedback_repo.create(record)
        return {
            "badcase_id": badcase_id,
            "status": "open",
            "ticket_ref": record["ticket_ref"],
            "sla_due_at": record["sla_due_at"],
        }

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
        """推进 badcase 状态；关闭必须有结构化回归用例。"""
        require_scope(ctx, "badcase:manage")
        require_admin(ctx)
        existing = require_found(
            await self.feedback_repo.get(badcase_id), "badcase"
        )
        merged = {**existing, **changes}
        if (
            changes.get("status") == "closed"
            and (
                not merged.get("regression_suite")
                or not merged.get("regression_case")
            )
        ):
            raise BadRequest(
                "closing a badcase requires regression_suite "
                "and regression_case"
            )
        if changes.get("status") == "fixed":
            changes.setdefault("fixed_at", datetime.now(UTC).isoformat())
        if (
            changes.get("status") in {"open", "reproduced"}
            and existing.get("status") in {"fixed", "closed"}
        ):
            changes["reopened_count"] = int(
                existing.get("reopened_count") or 0
            ) + 1
        if changes:
            await self.feedback_repo.update(badcase_id, changes)
        if changes.get("status") == "closed" and merged.get("ticket_ref"):
            try:
                if self.ticket_port is not None:
                    await self.ticket_port.close(
                        merged["ticket_ref"], changes.get("comment", "")
                    )
            except Exception:
                logger.exception("closing ticket failed: %s", badcase_id)
        return {"ok": True}
