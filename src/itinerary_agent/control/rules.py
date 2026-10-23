"""差标规则模型与 YAML 加载。

规则来自制度表格编译或人工维护；source_clause_id 用于回引制度条款。
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Rule(BaseModel):
    id: str
    match: dict = Field(default_factory=dict)
    category: str
    limit: float | None = None
    constraint: dict = Field(default_factory=dict)
    severity: str = "warn"
    allow_approval: bool = False
    source_clause_id: str | None = None
    policy_version: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None


class PolicyRules(BaseModel):
    version: str
    tenant_id: str
    defaults: dict = Field(default_factory=dict)
    rules: list[Rule] = Field(default_factory=list)


def load_rules(path: Path) -> PolicyRules:
    return PolicyRules.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )
