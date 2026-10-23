"""差标求值。

纯函数、无外部调用：同样的输入永远得到同样的结果，便于审计和测试。
模型不能改变这里的判定，只能用只读规则做解释。
"""

from itinerary_agent.control.rules import PolicyRules
from itinerary_agent.domain.models import (
    PolicyResult,
    SearchResults,
    TripRequest,
    UserProfile,
    Violation,
)

# demo 城市等级；生产应从企业主数据或制度表格读取。
CITY_TIERS = {
    "北京": 1, "上海": 1, "广州": 1, "深圳": 1,
    "杭州": 2, "成都": 2, "武汉": 2, "南京": 2,
}


def _city_tier(city: str | None) -> int:
    return CITY_TIERS.get(city or "", 3)


def _is_effective(rule, request: TripRequest) -> bool:
    """按出行日期过滤失效/未生效规则。"""
    date = request.start_date or ""
    if rule.effective_from and date and date < rule.effective_from:
        return False
    return not (rule.effective_to and date and date > rule.effective_to)


def _matches(rule, user: UserProfile, request: TripRequest) -> bool:
    levels = rule.match.get("employee_level")
    if levels and user.employee_level not in levels:
        return False
    tiers = rule.match.get("city_tier")
    if tiers and _city_tier(request.destination_city) not in tiers:
        return False
    return _is_effective(rule, request)


def check_policy(request: TripRequest, options: SearchResults,
                 user: UserProfile, rules: PolicyRules) -> PolicyResult:
    violations: list[Violation] = []
    requires_approval = False

    hotel_rules = [
        rule for rule in rules.rules
        if rule.category == "hotel" and _matches(rule, user, request)
    ]
    for rule in hotel_rules:
        for hotel in options.hotels:
            if rule.limit is not None and hotel.price_per_night > rule.limit:
                violations.append(Violation(
                    rule_id=rule.id, category="hotel", severity=rule.severity,
                    message=(
                        f"{hotel.hotel_name} 每晚 {hotel.price_per_night} "
                        f"超过标准 {rule.limit}"
                    ),
                    limit=rule.limit, actual=hotel.price_per_night,
                    source_clause_id=rule.source_clause_id,
                ))
                requires_approval = requires_approval or rule.allow_approval

    flight_rules = [
        rule for rule in rules.rules
        if rule.category == "flight" and _matches(rule, user, request)
    ]
    for rule in flight_rules:
        for flight in options.flights:
            if rule.limit is not None and flight.price > rule.limit:
                violations.append(Violation(
                    rule_id=rule.id, category="flight", severity=rule.severity,
                    message=(
                        f"{flight.flight_no} 票价 {flight.price} "
                        f"超过标准 {rule.limit}"
                    ),
                    limit=rule.limit, actual=flight.price,
                    source_clause_id=rule.source_clause_id,
                ))
                requires_approval = requires_approval or rule.allow_approval
            allowed_cabins = rule.constraint.get("cabin", [])
            if allowed_cabins and flight.cabin not in allowed_cabins:
                violations.append(Violation(
                    rule_id=rule.id, category="flight", severity=rule.severity,
                    message=f"{flight.flight_no} 舱位 {flight.cabin} 不符合标准",
                    source_clause_id=rule.source_clause_id,
                ))
                requires_approval = requires_approval or rule.allow_approval

    # 没有精确规则时回落到企业默认标准；默认值也缺失则拒绝。
    if not hotel_rules and options.hotels:
        default_limit = rules.defaults.get("hotel", {}).get("max_price_per_night")
        if default_limit is None:
            violations.append(Violation(
                rule_id="default-hotel", category="hotel", severity="block",
                message="无适用住宿标准，按制度要求拒绝",
            ))
        else:
            for hotel in options.hotels:
                if hotel.price_per_night > default_limit:
                    violations.append(Violation(
                        rule_id="default-hotel", category="hotel", severity="block",
                        message=(
                            f"{hotel.hotel_name} 超过默认住宿标准 {default_limit}"
                        ),
                        limit=default_limit, actual=hotel.price_per_night,
                    ))

    if not flight_rules and options.flights:
        default_limit = rules.defaults.get("flight", {}).get("max_price")
        if default_limit is None:
            violations.append(Violation(
                rule_id="default-flight", category="flight", severity="block",
                message="无适用机票标准，按制度要求拒绝",
            ))
        else:
            for flight in options.flights:
                if flight.price > default_limit:
                    violations.append(Violation(
                        rule_id="default-flight", category="flight", severity="block",
                        message=(
                            f"{flight.flight_no} 超过默认机票标准 {default_limit}"
                        ),
                        limit=default_limit, actual=flight.price,
                    ))

    passed = not any(violation.severity == "block" for violation in violations)
    return PolicyResult(
        passed=passed,
        requires_approval=requires_approval,
        violations=violations,
        policy_version=rules.version,
    )
