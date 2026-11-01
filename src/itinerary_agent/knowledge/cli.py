"""制度入库、重建和一致性检查 CLI。

用法：
    python -m itinerary_agent.knowledge.cli ingest --fixture <json>
    python -m itinerary_agent.knowledge.cli reindex
    python -m itinerary_agent.knowledge.cli check

默认连接 Settings 中的 PostgreSQL / Milvus。没有 Milvus 时使用
`--skip-vectors` 只维护结构化数据和关键词索引。
"""

import argparse
import asyncio
import hashlib
import json
import math
import random
import sys
from pathlib import Path

from itinerary_agent.domain.models import CallContext
from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.database import Database
from itinerary_agent.infra.repositories.policy_repository import (
    PostgresPolicyStore,
)
from itinerary_agent.knowledge.audit import audit_store
from itinerary_agent.knowledge.ingest import ingest_bundle
from itinerary_agent.knowledge.milvus_store import MilvusClauseStore
from itinerary_agent.knowledge.structure import (
    PolicyBundle,
    bundle_from_json,
    validate_bundle,
)


class HashEmbedder:
    """离线确定性 embedding；只用于本地结构验收，不具备语义能力。"""

    def __init__(self, dimensions: int):
        self.dimensions = dimensions

    async def embed(self, ctx, texts):
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            rng = random.Random(int.from_bytes(digest[:8], "big"))
            vector = [rng.uniform(-1.0, 1.0) for _ in range(self.dimensions)]
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Policy knowledge CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--tenant-id", default=None)
        p.add_argument("--policy-version", default=None)
        p.add_argument(
            "--skip-vectors", action="store_true",
            help="只写 PostgreSQL / 关键词索引，不连接 Milvus",
        )
        p.add_argument(
            "--embedder", choices=["auto", "dashscope", "hash"],
            default="auto",
        )
        p.add_argument("--json", action="store_true")

    ingest = sub.add_parser("ingest", help="导入结构化制度 JSON")
    ingest.add_argument("--fixture", type=Path, required=True)
    ingest.add_argument("--dry-run", action="store_true")
    common(ingest)

    reindex = sub.add_parser("reindex", help="重建关键词索引和 Milvus")
    common(reindex)

    check = sub.add_parser("check", help="检查条款树/边/表格一致性")
    check.add_argument("--warnings-as-errors", action="store_true")
    check.add_argument("--json", action="store_true")
    check.add_argument("--tenant-id", default=None)
    check.add_argument("--policy-version", default=None)
    return parser


def _settings() -> Settings:
    return Settings()


def _scope(settings: Settings, args) -> tuple[str, str]:
    return (
        args.tenant_id or "demo-company",
        args.policy_version or settings.policy_version,
    )


def _embedder(settings: Settings, mode: str):
    if mode == "hash":
        return HashEmbedder(settings.embedding_dimensions)
    if mode == "dashscope":
        from itinerary_agent.model_gateway.embeddings import (
            DashScopeEmbedder,
        )

        if settings.dashscope_api_key is None:
            raise SystemExit("DASHSCOPE_API_KEY is required for --embedder dashscope")
        return DashScopeEmbedder(settings)
    if settings.dashscope_api_key is not None:
        from itinerary_agent.model_gateway.embeddings import (
            DashScopeEmbedder,
        )

        return DashScopeEmbedder(settings)
    print(
        "warning: DASHSCOPE_API_KEY not set, using deterministic hash embeddings",
        file=sys.stderr,
    )
    return HashEmbedder(settings.embedding_dimensions)


def _bundle(path: Path, tenant_id: str, policy_version: str) -> PolicyBundle:
    bundle = bundle_from_json(json.loads(path.read_text(encoding="utf-8")))
    updates = {}
    if tenant_id != bundle.tenant_id:
        updates["tenant_id"] = tenant_id
    if policy_version != bundle.policy_version:
        updates["policy_version"] = policy_version
    if updates:
        bundle = bundle.model_copy(update=updates)
    validate_bundle(bundle)
    return bundle


async def _db(settings: Settings):
    db = Database(settings.database_url)
    await db.connect()
    store = PostgresPolicyStore(db)
    await store.init()
    return db, store


async def _ingest(args) -> int:
    settings = _settings()
    tenant_id, policy_version = _scope(settings, args)
    bundle = _bundle(args.fixture, tenant_id, policy_version)
    summary = {
        "doc_id": bundle.doc_id,
        "tenant_id": bundle.tenant_id,
        "policy_version": bundle.policy_version,
        "clauses": len(bundle.clauses),
        "tables": len(bundle.tables),
        "vectors": not args.skip_vectors,
    }
    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    db, store = await _db(settings)
    clause_store = None
    embedder = None
    try:
        if not args.skip_vectors:
            clause_store = MilvusClauseStore(settings)
            embedder = _embedder(settings, args.embedder)
        count = await ingest_bundle(bundle, store, clause_store, embedder)
        summary["ingested_clauses"] = count
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        await db.close()


async def _reindex(args) -> int:
    settings = _settings()
    tenant_id, policy_version = _scope(settings, args)
    db, store = await _db(settings)
    try:
        clauses = await store.list_clauses(tenant_id, policy_version)
        if not clauses:
            print(
                f"no clauses for tenant={tenant_id} version={policy_version}",
                file=sys.stderr,
            )
            return 1
        await store.reindex_keyword_indexes()
        summary = {
            "tenant_id": tenant_id,
            "policy_version": policy_version,
            "clauses": len(clauses),
            "keyword_index": "rebuilt",
            "vectors": not args.skip_vectors,
        }
        if not args.skip_vectors:
            refs = await store.list_references(tenant_id, policy_version)
            embedder = _embedder(settings, args.embedder)
            ctx = CallContext(
                trace_id="reindex", tenant_id=tenant_id, purpose="embed"
            )
            texts = [
                f"{clause['path']} {clause['title']} {clause['text']}"
                for clause in clauses
            ]
            vectors = await embedder.embed(ctx, texts)
            rows = []
            for clause, vector in zip(clauses, vectors, strict=True):
                rows.append({
                    "clause_id": clause["clause_id"],
                    "tenant_id": tenant_id,
                    "doc_id": clause["doc_id"],
                    "policy_version": policy_version,
                    "clause_type": clause["clause_type"],
                    "path": clause["path"],
                    "parent_id": clause.get("parent_id") or "",
                    "title": clause["title"],
                    "text": clause["text"],
                    "table_id": clause.get("table_id") or "",
                    "refs": refs.get(clause["clause_id"], []),
                    "effective_from": clause.get("effective_from") or "",
                    "effective_to": clause.get("effective_to") or "",
                    "embedding": list(vector),
                })
            clause_store = MilvusClauseStore(settings)
            clause_store.reset()
            batch = max(1, settings.embedding_batch_size)
            for start in range(0, len(rows), batch):
                clause_store.upsert(rows[start:start + batch])
            summary["vectors_written"] = len(rows)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        await db.close()


async def _check(args) -> int:
    settings = _settings()
    tenant_id, policy_version = _scope(settings, args)
    db, store = await _db(settings)
    try:
        report = await audit_store(store, tenant_id, policy_version)
    finally:
        await db.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        return 1
    if args.warnings_as_errors and report["warnings"]:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "ingest":
        return asyncio.run(_ingest(args))
    if args.command == "reindex":
        return asyncio.run(_reindex(args))
    return asyncio.run(_check(args))


if __name__ == "__main__":
    sys.exit(main())
