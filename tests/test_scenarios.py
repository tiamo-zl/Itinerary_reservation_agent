"""12 个端到端/集成场景。

主链路走真实 HTTP + SSE；制度检索场景直接调用 KnowledgeService，
避免为了测试再起 Milvus。
"""

from fastapi.testclient import TestClient

from itinerary_agent.control.rules import PolicyRules
from itinerary_agent.control.service import ControlService
from itinerary_agent.domain.models import (
    ApprovalStatus,
    PolicyFilters,
    PolicyTable,
    TaskSnapshot,
    TaskStatus,
)
from itinerary_agent.knowledge.policy_store import PolicyStore
from itinerary_agent.knowledge.service import KnowledgeService
from tests.db_utils import open_test_db
from tests.scenarios import (
    PLAN,
    UNDERSTAND,
    DegradedKnowledge,
    EmptyFlightInventory,
    EmptyHotelInventory,
    FailingFlightInventory,
    FailingHotelInventory,
    last_event,
    make_app,
    make_policy_service,
    post_sse,
    task_id_of,
)

SELECT = {"action": "select", "selected": {"flight_id": "f2", "hotel_id": "h1"}}


def _chat(client, message, user):
    return post_sse(client, "/chat", {"message": message}, user)


def _resume(client, task_id, payload, user):
    return post_sse(client, f"/tasks/{task_id}/resume", payload, user)


async def test_normal_booking(tmp_path):
    """正常链路：查询 → 差标通过 → 确认 → 下单。"""
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        events = _chat(client, "下周二去北京", "u002")
        task_id = task_id_of(events)
        assert last_event(events, "interrupt")

        resumed = _resume(client, task_id, SELECT, "u002")
        assert last_event(resumed, "result")["data"]["status"] == "COMPLETED"


async def test_over_policy_requires_approval(tmp_path):
    """超标链路：审批 interrupt → 审批通过 → 确认 → 下单。"""
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        events = _chat(client, "下周二去北京", "u001")
        task_id = task_id_of(events)
        interrupt = last_event(events, "interrupt")
        assert interrupt["data"]["human_request"]["kind"] == "approval"

        approved = _resume(
            client, task_id,
            {"action": "continue", "approval_status": "approved"},
            "u001",
        )
        assert last_event(approved, "interrupt")

        completed = _resume(client, task_id, SELECT, "u001")
        assert last_event(completed, "result")["data"]["status"] == "COMPLETED"


async def test_approval_rejected(tmp_path):
    """审批驳回：管理员拒绝后回到人工处理。"""
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        events = _chat(client, "下周二去北京", "u001")
        task_id = task_id_of(events)
        approval_id = last_event(events, "interrupt")["data"]["human_request"][
            "approval_id"
        ]

        admin = client.post(
            f"/admin/approvals/{approval_id}/reject",
            headers={"X-Mock-User": "u002"},
            json={"comment": "超标"},
        )
        assert admin.status_code == 200

        rejected = _resume(
            client, task_id,
            {"action": "continue", "approval_status": "rejected", "comment": "超标"},
            "u001",
        )
        message = last_event(rejected, "interrupt")["data"]["human_request"]["message"]
        assert "超标" in message or "驳回" in message
        task = client.get(f"/tasks/{task_id}").json()
        assert task["status"] == "WAITING_HUMAN"


async def test_amendment_invalidates_downstream(tmp_path):
    """修改需求后 revision+1，旧结果失效并重新规划。"""
    app, _ = make_app(tmp_path, script=[UNDERSTAND, PLAN, PLAN])
    with TestClient(app) as client:
        events = _chat(client, "下周二去北京", "u002")
        task_id = task_id_of(events)
        assert last_event(events, "interrupt")

        amended = _resume(
            client, task_id,
            {
                "action": "modify",
                "amended_request": {
                    "origin_city": "上海",
                    "destination_city": "上海",
                    "start_date": "2026-11-10",
                    "end_date": "2026-11-12",
                },
            },
            "u002",
        )
        assert last_event(amended, "interrupt")
        task = client.get(f"/tasks/{task_id}").json()
        assert task["revision"] == 1


async def test_no_results_asks_human(tmp_path):
    """库存为空时停在人工确认，不伪造方案。"""
    app, _ = make_app(
        tmp_path,
        script=[UNDERSTAND, PLAN],
        flight_inventory=EmptyFlightInventory(),
        hotel_inventory=EmptyHotelInventory(),
    )
    with TestClient(app) as client:
        events = _chat(client, "去北京", "u002")
        task_id = task_id_of(events)
        assert last_event(events, "interrupt")
        assert client.get(f"/tasks/{task_id}").json()["status"] == "WAITING_HUMAN"


async def test_pause_resume_cancel(tmp_path):
    """暂停后可继续；取消是终态。"""
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        events = _chat(client, "去北京", "u002")
        task_id = task_id_of(events)
        paused = _resume(client, task_id, {"action": "pause"}, "u002")
        assert last_event(paused, "result")["data"]["status"] == "PAUSED"

        resumed = _resume(client, task_id, {"action": "continue"}, "u002")
        assert last_event(resumed, "result")["data"]["status"] == "COMPLETED"

    cancel_app, _ = make_app(tmp_path / "cancel", script=[UNDERSTAND, PLAN])
    with TestClient(cancel_app) as client:
        events = _chat(client, "去北京", "u002")
        task_id = task_id_of(events)
        cancelled = _resume(client, task_id, {"action": "cancel"}, "u002")
        assert last_event(cancelled, "result")["data"]["status"] == "CANCELLED"


async def test_tool_failure_and_rag_degraded(tmp_path):
    """工具失败与知识降级都不应拖垮主流程。"""
    app, _ = make_app(
        tmp_path,
        script=[UNDERSTAND, PLAN],
        flight_inventory=FailingFlightInventory(),
        hotel_inventory=FailingHotelInventory(),
        knowledge=DegradedKnowledge(),
    )
    with TestClient(app) as client:
        events = _chat(client, "去北京", "u002")
        task_id = task_id_of(events)
        # 工具失败被归一化，知识降级不阻塞主流程，最终停在确认节点。
        assert last_event(events, "interrupt")
        assert client.get(f"/tasks/{task_id}").json()["status"] == "WAITING_HUMAN"


async def test_booking_without_approval_denied():
    """Guard 拒绝未审批的下单动作。"""
    class _NoopAudit:
        async def record(self, *args, **kwargs):
            return None

    rules = PolicyRules(version="2026.1", tenant_id="demo-company", rules=[])
    service = ControlService(rules, _NoopAudit())
    snapshot = TaskSnapshot(
        task_id="t", status=TaskStatus.EXECUTING, revision=1,
        policy_passed=False, requires_approval=True,
        approval_status=ApprovalStatus.PENDING, confirmed=True,
    )
    ctx = type("Ctx", (), {"roles": ["employee"]})()
    assert service.guard(ctx, "book_flight", snapshot).code == "APPROVAL_REQUIRED"


async def test_cross_clause_citation(tmp_path):
    """检索应扩展被引用条款并带上 citations。"""
    db, service = await make_policy_service(
        tmp_path,
        clauses=[
            {"clause_id": "c1", "path": "p/c1", "title": "住宿标准",
             "text": "住宿标准见附表二。", "refs": ["c2"], "table_id": None},
            {"clause_id": "c2", "path": "p/c2", "title": "附表二",
             "text": "标准表。", "table_id": None},
        ],
        dense_ids=["c1"],
    )
    ctx = type("Ctx", (), {"trace_id": "t", "tenant_id": "demo-company"})()
    result = await service.search_policy(ctx, "住宿标准")
    assert {"c1", "c2"} <= set(result.citations)
    await db.close()


async def test_exception_clause_applied(tmp_path):
    """例外条款应进入检索上下文。"""
    db, service = await make_policy_service(
        tmp_path,
        clauses=[
            {"clause_id": "c1", "path": "p/c1", "title": "住宿标准",
             "text": "住宿上限 500。", "exception_to": None,
             "exception": "c3", "table_id": None},
            {"clause_id": "c3", "path": "p/c3", "title": "例外",
             "text": "紧急会议可特批。", "table_id": None},
        ],
        dense_ids=["c1"],
    )
    # 例外关系用 edge 表达；这里补一条 c1 -> c3 的 exception_to。
    await service.policy_store.add_edge("c1", "exception_to", "c3")
    ctx = type("Ctx", (), {"trace_id": "t", "tenant_id": "demo-company"})()
    result = await service.search_policy(ctx, "住宿")
    assert "c3" in result.citations
    await db.close()


async def test_table_row_selection(tmp_path):
    """表格按职级/城市过滤，只返回适用行。"""
    table = PolicyTable(
        table_id="t1", source_clause_id="c1",
        columns=["职级", "城市", "上限"],
        rows=[
            {"职级": "L2", "城市": "北京", "上限": 500},
            {"职级": "L3", "城市": "北京", "上限": 700},
        ],
    )
    db, service = await make_policy_service(
        tmp_path,
        clauses=[{
            "clause_id": "c1", "path": "p/c1", "title": "住宿标准",
            "text": "标准见附表。", "table_id": "t1",
        }],
        dense_ids=["c1"], tables=[table],
    )
    ctx = type("Ctx", (), {"trace_id": "t", "tenant_id": "demo-company"})()
    result = await service.search_policy(
        ctx, "住宿标准", filters=PolicyFilters(employee_level="L2", city_tier=1)
    )
    assert result.tables[0].rows == [{"职级": "L2", "城市": "北京", "上限": 500}]
    await db.close()


async def test_policy_version_and_insufficient(tmp_path):
    """只检索当前版本；无命中返回 insufficient。"""
    db = await open_test_db()
    store = PolicyStore(db)
    await store.init()
    for clause_id, version, text in [
        ("c1", "2026.1", "2026 版住宿标准 500。"),
        ("c2", "2025.1", "2025 版住宿标准 400。"),
    ]:
        await store.upsert_clause({
            "clause_id": clause_id, "tenant_id": "demo-company",
            "doc_id": "travel-policy", "parent_id": None,
            "path": f"p/{clause_id}", "clause_type": "clause",
            "title": "住宿标准", "text": text, "table_id": None,
            "policy_version": version, "effective_from": "2025-01-01",
            "effective_to": None, "order_no": int(clause_id[1:]),
        })

    hits = await store.keyword_search("demo-company", "2026.1", "住宿标准", 5)
    assert [hit["clause_id"] for hit in hits] == ["c1"]

    class _Embedder:
        async def embed(self, ctx, texts):
            return [[0.0] * 1024 for _ in texts]

    class _Dense:
        def search(self, tenant_id, policy_version, vector, limit=10):
            return []

    service = KnowledgeService(
        embedder=_Embedder(), policy_store=store, dense_store=_Dense(),
        policy_version="2026.1", seed_top_k=8, graph_hops=1,
        max_expanded_clauses=20,
    )
    ctx = type("Ctx", (), {"trace_id": "t", "tenant_id": "demo-company"})()
    result = await service.search_policy(ctx, "不存在的制度问题")
    assert result.insufficient is True
    await db.close()
