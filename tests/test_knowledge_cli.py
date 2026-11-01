"""知识入库 CLI 的结构化导入、审计与重建辅助。"""

import json
from pathlib import Path

from itinerary_agent.infra.repositories.policy_repository import (
    PostgresPolicyStore,
)
from itinerary_agent.knowledge.audit import audit_store
from itinerary_agent.knowledge.cli import HashEmbedder
from itinerary_agent.knowledge.ingest import ingest_bundle
from itinerary_agent.knowledge.structure import bundle_from_json
from tests.db_utils import open_test_db

FIXTURE = Path("config/policies/docs/demo-travel-policy.json")


async def _ingest_fixture(store) -> None:
    bundle = bundle_from_json(json.loads(FIXTURE.read_text(encoding="utf-8")))
    await ingest_bundle(bundle, store, clause_store=None, embedder=None)


async def test_ingest_writes_structure_and_audit_passes(tmp_path):
    db = await open_test_db()
    store = PostgresPolicyStore(db)
    await store.init()
    await _ingest_fixture(store)

    clauses = await store.list_clauses("demo-company", "2026.1")
    assert len(clauses) == 4
    assert {clause["clause_id"] for clause in clauses} == {
        "ch3", "c1", "c2", "c3",
    }
    refs = await store.list_references("demo-company", "2026.1")
    assert refs["c1"] == ["c2"]

    report = await audit_store(store, "demo-company", "2026.1")
    assert report["ok"] is True
    assert report["counts"]["clauses"] == 4
    assert report["counts"]["tables"] == 1
    await db.close()


async def test_audit_reports_dangling_edge(tmp_path):
    db = await open_test_db()
    store = PostgresPolicyStore(db)
    await store.init()
    await _ingest_fixture(store)
    await store.add_edge("c1", "references", "missing")

    report = await audit_store(store, "demo-company", "2026.1")

    assert report["ok"] is False
    assert any("dangling target missing" in item for item in report["errors"])
    await db.close()


async def test_hash_embedder_is_deterministic(tmp_path):
    embedder = HashEmbedder(8)
    first = await embedder.embed(None, ["住宿标准"])
    second = await embedder.embed(None, ["住宿标准"])
    assert first == second
    assert len(first[0]) == 8
    assert abs(sum(value * value for value in first[0]) - 1.0) < 1e-6
