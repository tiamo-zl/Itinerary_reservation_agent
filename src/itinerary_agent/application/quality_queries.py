"""近线质量 findings 查询。"""

from itinerary_agent.application.access import (
    require_admin,
    require_scope,
)
from itinerary_agent.application.pagination import normalize_limit
from itinerary_agent.domain.models import RequestContext


class QualityQueryService:
    def __init__(self, finding_repo):
        self.finding_repo = finding_repo

    async def list_findings(self, ctx: RequestContext,
                            limit: int = 100) -> dict:
        require_scope(ctx, "badcase:manage")
        require_admin(ctx)
        return {
            "findings": await self.finding_repo.list_recent(
                normalize_limit(limit)
            )
        }
