"""控制层门面。

编排层只依赖这个类，不直接 import 规则求值/Guard 的内部实现。
"""

from itinerary_agent.control.audit import AuditLog
from itinerary_agent.control.guard import guard_action
from itinerary_agent.control.policy import check_policy
from itinerary_agent.control.rules import PolicyRules
from itinerary_agent.domain.models import (
    GuardResult,
    PolicyResult,
    RequestContext,
    SearchResults,
    TaskSnapshot,
    TripRequest,
    UserProfile,
)


class ControlService:
    def __init__(self, rules: PolicyRules, audit: AuditLog):
        self.rules = rules
        self.audit = audit

    def check_policy(self, request: TripRequest, options: SearchResults,
                     user: UserProfile) -> PolicyResult:
        return check_policy(request, options, user, self.rules)

    def guard(self, ctx: RequestContext, action: str,
              snapshot: TaskSnapshot) -> GuardResult:
        return guard_action(action, snapshot, ctx.roles)
