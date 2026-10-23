from itinerary_agent.knowledge.structure import (
    PolicyBundle,
    resolve_references,
    validate_bundle,
)


def test_bundle_keeps_hierarchy_and_resolves_edges():
    # 引用文本（"附表二"）应解析到条款 ID；解析不到的进入 unresolved。
    bundle = PolicyBundle.model_validate({
        "doc_id": "travel-policy", "tenant_id": "demo-company",
        "policy_version": "2026.1",
        "clauses": [
            {"clause_id": "ch3", "parent_id": None, "path": "travel-policy/ch3",
             "clause_type": "chapter", "title": "住宿", "text": "住宿标准见 c1。",
             "refs": [], "ref_texts": [], "exceptions": [], "table_id": None, "order_no": 1},
            {"clause_id": "c1", "parent_id": "ch3", "path": "travel-policy/ch3/c1",
             "clause_type": "clause", "title": "住宿标准",
             "text": "一线城市住宿上限 500 元，具体见附表二，另见第3.2条。",
             "refs": ["c2"], "ref_texts": ["附表二", "第3.2条"],
             "exceptions": ["c3"], "table_id": "t1", "order_no": 2},
            {"clause_id": "c2", "parent_id": "ch3", "path": "travel-policy/ch3/c2",
             "clause_type": "clause", "title": "附表二", "text": "标准表见 t1。",
             "refs": [], "ref_texts": [], "exceptions": [], "table_id": "t1", "order_no": 3},
            {"clause_id": "c3", "parent_id": "ch3", "path": "travel-policy/ch3/c3",
             "clause_type": "clause", "title": "例外", "text": "紧急会议可特批。",
             "refs": [], "ref_texts": [], "exceptions": [], "table_id": None, "order_no": 4},
        ],
        "tables": [{"table_id": "t1", "source_clause_id": "c1",
                    "columns": ["职级", "城市", "上限"],
                    "rows": [{"职级": "L2", "城市": "一线", "上限": 500}]}],
    })

    validate_bundle(bundle)
    edges, unresolved = resolve_references(bundle)
    assert ("c1", "references", "c2") in edges
    assert ("c1", "exception_to", "c3") in edges
    assert unresolved == [("c1", "第3.2条")]
