from itinerary_agent.control.policy import check_policy
from itinerary_agent.control.rules import PolicyRules, Rule
from itinerary_agent.domain.models import HotelOption, SearchResults, TripRequest, UserProfile


def _user(level: str = "L1") -> UserProfile:
    return UserProfile(
        user_id="u", tenant_id="demo-company", name="A",
        employee_level=level, department="D", city="上海",
    )


def _hotel(price: float, city: str = "北京") -> HotelOption:
    return HotelOption(
        option_id="h1", hotel_name="H", city=city, area="王府井",
        room_type="大床", price_per_night=price, refundable=True,
        distance_to_center_km=1.0,
    )


def test_over_budget_hotel_requires_approval():
    rules = PolicyRules(
        version="2026.1", tenant_id="demo-company", defaults={},
        rules=[Rule(
            id="hotel-L1", match={"employee_level": ["L1"]},
            category="hotel", limit=500, severity="block", allow_approval=True,
            source_clause_id="c1",
        )],
    )
    result = check_policy(
        TripRequest(destination_city="北京"),
        SearchResults(hotels=[_hotel(800)]),
        _user("L1"),
        rules,
    )
    assert result.passed is False
    assert result.requires_approval is True
    assert result.violations[0].source_clause_id == "c1"


def test_no_matching_rule_uses_defaults():
    # 没有精确规则时不能默认放行，应回落到默认标准。
    rules = PolicyRules(
        version="2026.1", tenant_id="demo-company",
        defaults={"hotel": {"max_price_per_night": 600}}, rules=[],
    )
    result = check_policy(
        TripRequest(destination_city="北京"),
        SearchResults(hotels=[_hotel(800)]),
        _user("L9"),
        rules,
    )
    assert result.passed is False
    assert result.violations[0].rule_id == "default-hotel"


def test_city_tier_filter_excludes_rule():
    # 规则限定一线城市；成都属于二线，应走默认标准而不是一线 500。
    rules = PolicyRules(
        version="2026.1", tenant_id="demo-company",
        defaults={"hotel": {"max_price_per_night": 1000}},
        rules=[Rule(
            id="hotel-tier1",
            match={"employee_level": ["L2"], "city_tier": [1]},
            category="hotel", limit=500, severity="block",
        )],
    )
    result = check_policy(
        TripRequest(destination_city="成都"),
        SearchResults(hotels=[_hotel(800, city="成都")]),
        _user("L2"),
        rules,
    )
    assert result.passed is True
    assert all(v.rule_id != "hotel-tier1" for v in result.violations)
