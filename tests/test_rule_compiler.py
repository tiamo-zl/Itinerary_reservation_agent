from itinerary_agent.control.rules_compiler import compile_rules_from_table
from itinerary_agent.domain.models import PolicyTable


def test_compile_rules_from_policy_table():
    # 差标表格的每一行编译成规则，并保留来源条款。
    table = PolicyTable(
        table_id="t1", source_clause_id="c1",
        columns=["职级", "城市", "上限"],
        rows=[{"职级": "L2", "城市": "一线", "上限": 500}],
    )
    rules = compile_rules_from_table(table, "demo-company", "2026.1", "2026-01-01")
    rule = rules.rules[0]
    assert rule.limit == 500
    assert rule.source_clause_id == "c1"
    assert rule.match["employee_level"] == ["L2"]
    assert rule.match["city_tier"] == [1]
