"""制度入库：条款树 + 引用边 + 表格 + 向量。

流程：校验结构 → 写 SQLite → 解析引用 → 写 Milvus。
解析失败的引用进入人工校对队列，不阻塞其他条款入库。
"""

from itinerary_agent.domain.models import CallContext
from itinerary_agent.knowledge.structure import (
    PolicyBundle,
    resolve_references,
    validate_bundle,
)


async def ingest_bundle(bundle: PolicyBundle, policy_store, clause_store,
                        embedder) -> int:
    """把一份结构化制度写入 SQLite 和 Milvus。

    步骤：
    1. 校验条款树/引用/表格完整性；
    2. 写入条款；
    3. 解析引用并写入边，未解析引用进入人工校对；
    4. 写入表格；
    5. 生成条款向量并写入 Milvus。
    """
    # 步骤 1：入库前校验，避免悬空引用/表格。
    validate_bundle(bundle)
    await policy_store.init()

    # 步骤 2：逐条写入结构化条款。
    for clause in bundle.clauses:
        await policy_store.upsert_clause({
            "clause_id": clause.clause_id, "tenant_id": bundle.tenant_id,
            "doc_id": bundle.doc_id, "parent_id": clause.parent_id,
            "path": clause.path, "clause_type": clause.clause_type,
            "title": clause.title, "text": clause.text, "table_id": clause.table_id,
            "policy_version": bundle.policy_version,
            "effective_from": bundle.effective_from,
            "effective_to": bundle.effective_to, "order_no": clause.order_no,
        })

    # 步骤 3：解析 ID 引用和文本引用；失败的引用进入人工校对队列。
    edges, unresolved = resolve_references(bundle)
    for source, relation, target in edges:
        await policy_store.add_edge(source, relation, target)
    for clause_id, ref_text in unresolved:
        await policy_store.add_review(clause_id, ref_text, "unresolved_reference")

    # 步骤 4：表格保持结构化存储，不做文本切分。
    for table in bundle.tables:
        await policy_store.upsert_table(table)

    # 步骤 5：条款级 embedding；文本带路径和标题，帮助区分同名条款。
    # --skip-vectors 时只写结构化数据，不依赖 Milvus/embedding。
    if clause_store is None or embedder is None:
        return len(bundle.clauses)
    texts = [f"{clause.path} {clause.title} {clause.text}" for clause in bundle.clauses]
    call_ctx = CallContext(
        trace_id="ingest", tenant_id=bundle.tenant_id, purpose="embed"
    )
    vectors = await embedder.embed(call_ctx, texts)

    rows = []
    for clause, vector in zip(bundle.clauses, vectors, strict=True):
        refs = [
            target for source, relation, target in edges
            if source == clause.clause_id and relation == "references"
        ]
        rows.append({
            "clause_id": clause.clause_id, "tenant_id": bundle.tenant_id,
            "doc_id": bundle.doc_id, "policy_version": bundle.policy_version,
            "clause_type": clause.clause_type, "path": clause.path,
            "parent_id": clause.parent_id or "", "title": clause.title,
            "text": clause.text, "table_id": clause.table_id or "",
            "refs": refs, "effective_from": bundle.effective_from,
            "effective_to": bundle.effective_to or "", "embedding": list(vector),
        })

    clause_store.ensure_collection()
    clause_store.upsert(rows)
    return len(rows)
