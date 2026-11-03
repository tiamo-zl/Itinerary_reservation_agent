"""近线质量 findings 与 judge 人工复核。"""

import logging

from itinerary_agent.application.access import (
    require_admin,
    require_found,
    require_scope,
)
from itinerary_agent.application.errors import BadRequest
from itinerary_agent.application.pagination import normalize_limit
from itinerary_agent.domain.models import RequestContext

logger = logging.getLogger(__name__)


class QualityQueryService:
    def __init__(self, finding_repo, judge_repo=None, audit=None):
        self.finding_repo = finding_repo
        self.judge_repo = judge_repo
        self.audit = audit

    async def list_findings(self, ctx: RequestContext,
                            limit: int = 100) -> dict:
        require_scope(ctx, "badcase:manage")
        require_admin(ctx)
        return {
            "findings": await self.finding_repo.list_recent(
                normalize_limit(limit)
            )
        }

    async def list_judgements(self, ctx: RequestContext,
                              limit: int = 100,
                              review_status: str | None = None,
                              verdict: str | None = None) -> dict:
        require_scope(ctx, "badcase:manage")
        require_admin(ctx)
        if self.judge_repo is None:
            return {"judgements": []}
        return {
            "judgements": await self.judge_repo.list_recent(
                normalize_limit(limit), review_status, verdict
            )
        }

    async def review_judgement(self, ctx: RequestContext, judge_id: str,
                               human_score: int, human_verdict: str,
                               comment: str = "") -> dict:
        """人工复核一条 judge 结果；judge 只是信号，人工标签才入库。"""
        require_scope(ctx, "badcase:manage")
        require_admin(ctx)
        if self.judge_repo is None:
            raise BadRequest("judge repository is not configured")
        if human_verdict not in {"pass", "fail"}:
            raise BadRequest("human_verdict must be pass or fail")
        if not 0 <= human_score <= 5:
            raise BadRequest("human_score must be between 0 and 5")
        row = require_found(await self.judge_repo.get(judge_id), "judgement")
        await self.judge_repo.review(
            judge_id, human_score, human_verdict, ctx.user_id, comment
        )
        if self.audit is not None:
            try:
                await self.audit.record(
                    ctx.trace_id, row.get("task_id"), ctx.user_id,
                    "judge.review",
                    {
                        "judge_id": judge_id,
                        "human_score": human_score,
                        "human_verdict": human_verdict,
                    },
                    [], row.get("prompt_version", ""), human_verdict, comment,
                )
            except Exception:
                logger.exception("judge review audit failed: %s", judge_id)
        return {"ok": True, "judgement": await self.judge_repo.get(judge_id)}
