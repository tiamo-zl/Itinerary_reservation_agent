"""制度数据一致性与重建前检查。"""


async def audit_store(policy_store, tenant_id: str,
                      policy_version: str) -> dict:
    """检查条款树、引用边、表格和人工校对队列。

    返回结构：
    {
      "ok": bool,
      "errors": [...],
      "warnings": [...],
      "counts": {...},
    }
    """
    clauses = await policy_store.list_clauses(tenant_id, policy_version)
    edges = await policy_store.list_edges(tenant_id, policy_version)
    reviews = await policy_store.list_pending_reviews()
    errors: list[str] = []
    warnings: list[str] = []

    ids = {clause["clause_id"] for clause in clauses}
    paths: dict[str, str] = {}
    table_cache: dict[str, bool] = {}

    for clause in clauses:
        clause_id = clause["clause_id"]
        if not clause.get("title"):
            errors.append(f"{clause_id}: empty title")
        if not clause.get("text"):
            warnings.append(f"{clause_id}: empty text")
        parent = clause.get("parent_id")
        if parent and parent not in ids:
            errors.append(f"{clause_id}: missing parent {parent}")
        path = clause.get("path")
        if path in paths:
            errors.append(
                f"{clause_id}: duplicate path {path} (also {paths[path]})"
            )
        elif path:
            paths[path] = clause_id
        table_id = clause.get("table_id")
        if table_id:
            if table_id not in table_cache:
                table_cache[table_id] = (
                    await policy_store.get_table(table_id) is not None
                )
            if not table_cache[table_id]:
                errors.append(f"{clause_id}: missing table {table_id}")

    valid_relations = {"references", "exception_to", "child_of"}
    for edge in edges:
        source = edge["source_id"]
        target = edge["target_id"]
        relation = edge["relation"]
        if target not in ids:
            errors.append(f"{source}: {relation} dangling target {target}")
        if relation not in valid_relations:
            warnings.append(f"{source}: unknown relation {relation}")

    for review in reviews:
        warnings.append(
            f"{review['clause_id']}: unresolved reference "
            f"{review['ref_text']!r} ({review['reason']})"
        )

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "clauses": len(clauses),
            "edges": len(edges),
            "tables": sum(1 for value in table_cache.values() if value),
            "pending_reviews": len(reviews),
        },
    }
