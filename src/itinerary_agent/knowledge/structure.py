"""制度结构模型与引用解析。

demo 从结构化 JSON fixture 入库；生产解析器（Docling/LLM 辅助）最终也输出
同样的 PolicyBundle，因此下游检索代码不需要知道解析方式。
"""

from pydantic import BaseModel, Field

from itinerary_agent.domain.models import PolicyTable


class ParsedClause(BaseModel):
    clause_id: str
    parent_id: str | None = None
    path: str
    clause_type: str
    title: str
    text: str
    refs: list[str] = Field(default_factory=list)          # 已解析的 clause_id
    ref_texts: list[str] = Field(default_factory=list)     # 原始引用文本
    exceptions: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    table_id: str | None = None
    order_no: int


class PolicyBundle(BaseModel):
    doc_id: str
    tenant_id: str
    policy_version: str
    effective_from: str = "2026-01-01"
    effective_to: str | None = None
    clauses: list[ParsedClause]
    tables: list[PolicyTable] = Field(default_factory=list)


def build_alias_map(bundle: PolicyBundle) -> dict[str, str]:
    """把条款 ID、标题、路径和显式别名映射到 clause_id。"""
    alias: dict[str, str] = {}
    for clause in bundle.clauses:
        alias[clause.clause_id] = clause.clause_id
        alias[clause.path] = clause.clause_id
        alias[clause.title] = clause.clause_id
        for name in clause.aliases:
            alias[name] = clause.clause_id
    return alias


def resolve_references(
    bundle: PolicyBundle,
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]]]:
    """把 ID 引用与文本引用统一成边；返回解析失败的引用。"""
    alias = build_alias_map(bundle)
    edges: list[tuple[str, str, str]] = []
    unresolved: list[tuple[str, str]] = []

    for clause in bundle.clauses:
        for ref in clause.refs:
            edges.append((clause.clause_id, "references", ref))
        for text in clause.ref_texts:
            target = alias.get(text)
            if target:
                edges.append((clause.clause_id, "references", target))
            else:
                unresolved.append((clause.clause_id, text))
        for exception in clause.exceptions:
            edges.append((clause.clause_id, "exception_to", exception))
        if clause.parent_id:
            edges.append((clause.clause_id, "child_of", clause.parent_id))

    return edges, unresolved


def validate_bundle(bundle: PolicyBundle) -> None:
    """入库前做结构校验，防止悬空父节点/引用/表格。"""
    ids = {clause.clause_id for clause in bundle.clauses}
    for clause in bundle.clauses:
        if clause.parent_id and clause.parent_id not in ids:
            raise ValueError(f"missing parent: {clause.parent_id}")
        for ref in clause.refs + clause.exceptions:
            if ref not in ids:
                raise ValueError(f"missing reference: {ref}")
    table_ids = {table.table_id for table in bundle.tables}
    for clause in bundle.clauses:
        if clause.table_id and clause.table_id not in table_ids:
            raise ValueError(f"missing table: {clause.table_id}")


def bundle_from_json(data: dict) -> PolicyBundle:
    return PolicyBundle.model_validate(data)
