"""端到端场景的共享装配。

所有场景默认离线：脚本化模型、mock 外部系统、共享 PostgreSQL 测试库。
"""

import json

from itinerary_agent.adapters.mock.inventory import MockHotelInventory
from itinerary_agent.adapters.mock.users import MockUserDirectory
from itinerary_agent.adapters.scripted_model import ScriptedModelGateway
from itinerary_agent.api.app import create_app
from itinerary_agent.domain.models import PolicyContext, PolicyTable
from itinerary_agent.infra.container import build_container
from itinerary_agent.infra.database import Database
from itinerary_agent.infra.repositories import PostgresPolicyStore
from itinerary_agent.knowledge.service import KnowledgeService
from tests.db_utils import TEST_DATABASE_URL, make_test_settings

UNDERSTAND = (
    '{"origin_city":"上海","destination_city":"北京",'
    '"start_date":"2026-11-03","end_date":"2026-11-05"}'
)
PLAN = '{"steps":["search_flights","search_hotels"]}'
RESPOND = "方案已生成。"


class EmptyFlightInventory:
    async def search(self, origin, destination, date):
        return []


class EmptyHotelInventory:
    async def search(self, city, check_in, check_out, area):
        return []


class FailingFlightInventory:
    async def search(self, origin, destination, date):
        raise RuntimeError("inventory down")


class FailingHotelInventory:
    async def search(self, city, check_in, check_out, area):
        raise RuntimeError("inventory down")


class DegradedKnowledge:
    async def search_policy(self, ctx, query, filters=None):
        return PolicyContext(
            clauses=[], tables=[], citations=[], policy_version="2026.1",
            degraded=True, insufficient=True,
        )


def make_app(tmp_path, script=None, **overrides):
    # tmp_path 保留在签名里兼容现有用例；测试库由 conftest 统一清理。
    settings = make_test_settings()
    container = build_container(settings)
    container.model = ScriptedModelGateway(script or [UNDERSTAND, PLAN, RESPOND])
    for key, value in overrides.items():
        setattr(container, key, value)
    return create_app(container), container


def parse_sse(text: str) -> list[dict]:
    """把 sse-starlette 输出解析成 [{type, data}]。"""
    events = []
    event_type = None
    for line in text.splitlines():
        if line.startswith("event:"):
            event_type = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            payload = json.loads(line.split(":", 1)[1].strip())
            events.append({"type": event_type, "data": payload})
    return events


def post_sse(client, path: str, payload: dict, user: str = "u001") -> list[dict]:
    with client.stream(
        "POST", path, json=payload, headers={"X-Mock-User": user}
    ) as response:
        text = "".join(response.iter_text())
    return parse_sse(text)


def last_event(events: list[dict], event_type: str) -> dict | None:
    for event in reversed(events):
        if event["type"] == event_type:
            return event
    return None


def task_id_of(events: list[dict]) -> str:
    return events[0]["data"]["task_id"]


class _FakeEmbedder:
    async def embed(self, ctx, texts):
        return [[0.1] * 1024 for _ in texts]


class _FakeDenseStore:
    def __init__(self, clause_ids):
        self.clause_ids = clause_ids

    def search(self, tenant_id, policy_version, vector, limit=10):
        return [
            {"clause_id": clause_id, "score": 1.0}
            for clause_id in self.clause_ids[:limit]
        ]


async def make_policy_service(tmp_path, clauses, dense_ids, tables=None):
    """构造带条款/边/表格的 KnowledgeService，用于制度场景。"""
    db = Database(TEST_DATABASE_URL)
    await db.connect()
    store = PostgresPolicyStore(db)
    await store.init()
    for clause in clauses:
        await store.upsert_clause({
            "tenant_id": "demo-company",
            "doc_id": "travel-policy",
            "parent_id": None,
            "clause_type": "clause",
            "policy_version": "2026.1",
            "effective_from": "2026-01-01",
            "effective_to": None,
            "order_no": int(clause["clause_id"][1:]),
            **clause,
        })
        for ref in clause.get("refs", []):
            await store.add_edge(clause["clause_id"], "references", ref)
        if clause.get("exception_to"):
            await store.add_edge(
                clause["clause_id"], "exception_to", clause["exception_to"]
            )
    for table in tables or []:
        await store.upsert_table(table)
    service = KnowledgeService(
        embedder=_FakeEmbedder(), policy_store=store,
        dense_store=_FakeDenseStore(dense_ids), policy_version="2026.1",
        seed_top_k=8, graph_hops=1, max_expanded_clauses=20,
    )
    return db, service


__all__ = [
    "PLAN",
    "RESPOND",
    "UNDERSTAND",
    "DegradedKnowledge",
    "EmptyFlightInventory",
    "EmptyHotelInventory",
    "FailingFlightInventory",
    "FailingHotelInventory",
    "MockHotelInventory",
    "MockUserDirectory",
    "PolicyTable",
    "last_event",
    "make_app",
    "make_policy_service",
    "parse_sse",
    "post_sse",
    "task_id_of",
]
