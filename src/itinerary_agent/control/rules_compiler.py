"""把制度表格行编译为差标规则。

生产环境应由规则治理流程审核后启用；demo 直接返回编译结果。
"""

from itinerary_agent.control.rules import PolicyRules, Rule
from itinerary_agent.domain.models import PolicyTable

# demo 的城市等级映射；生产应来自企业主数据。
CITY_TIER = {"一线": 1, "二线": 2, "三线": 3}


def compile_rules_from_table(table: PolicyTable, tenant_id: str,
                             policy_version: str,
                             effective_from: str | None = None) -> PolicyRules:
    rules: list[Rule] = []
    for index, row in enumerate(table.rows):
        level = row.get("职级")
        city = row.get("城市")
        limit = row.get("上限")
        if level is None or limit is None:
            continue
        rules.append(Rule(
            id=f"{table.table_id}-{index}",
            match={
                "employee_level": [level],
                "city_tier": [CITY_TIER.get(city, 0)],
            },
            category="hotel",
            limit=float(limit),
            severity="block",
            allow_approval=True,
            source_clause_id=table.source_clause_id,
            policy_version=policy_version,
            effective_from=effective_from,
        ))
    return PolicyRules(version=policy_version, tenant_id=tenant_id, rules=rules)
