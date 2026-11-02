"""评测 suite：槽位、差标、检索、审批、prompt 与 badcase。"""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from itinerary_agent.control.guard import guard_action
from itinerary_agent.control.policy import check_policy
from itinerary_agent.control.rules import PolicyRules, Rule
from itinerary_agent.domain.models import (
    ApprovalStatus,
    FlightOption,
    HotelOption,
    PolicyFilters,
    RequestContext,
    SearchResults,
    TaskSnapshot,
    TaskStatus,
    TripRequest,
    UserProfile,
)
from itinerary_agent.eval.loader import load_json
from itinerary_agent.eval.metrics import (
    mean,
    precision,
    recall_at_k,
    reciprocal_rank,
)
from itinerary_agent.eval.retrieval import (
    MemoryPolicyStore,
    StaticDenseStore,
    StaticEmbedder,
)
from itinerary_agent.knowledge.service import KnowledgeService
from itinerary_agent.orchestration.nodes.understand import (
    _load_json,
    normalize_payload,
)
from itinerary_agent.orchestration.service import apply_amendment

RECALL_K = 5


@dataclass
class SuiteResult:
    name: str
    total: int
    passed: int
    metrics: dict[str, float] = field(default_factory=dict)
    failures: list[dict] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 1.0


# ---------------------------------------------------------------- 槽位


def _materialize_slot(expected: dict, normalized: dict) -> dict:
    actual = {}
    for key in expected:
        if key == "start_weekday":
            value = normalized.get("start_date")
            actual[key] = (
                date.fromisoformat(value).weekday() if value else None
            )
        elif key == "duration_days":
            start = normalized.get("start_date")
            end = normalized.get("end_date")
            actual[key] = (
                (date.fromisoformat(end) - date.fromisoformat(start)).days
                if start and end else None
            )
        else:
            actual[key] = normalized.get(key)
    return actual


def _slot_passed(expected: dict, actual: dict) -> tuple[bool, int, int]:
    hits = sum(1 for key, value in expected.items() if actual.get(key) == value)
    return hits == len(expected), hits, len(expected)


def evaluate_slots(cases: list[dict],
                   prompt_version: str | None = None) -> SuiteResult:
    total_fields = 0
    hit_fields = 0
    exact = 0
    failures: list[dict] = []
    for case in cases:
        if prompt_version is not None and case.get("prompt_version") != prompt_version:
            continue
        normalized = normalize_payload(
            case["raw"], today=date.fromisoformat(case["today"])
        )
        actual = _materialize_slot(case["expected"], normalized)
        ok, hits, count = _slot_passed(case["expected"], actual)
        exact += int(ok)
        hit_fields += hits
        total_fields += count
        if not ok:
            failures.append({
                "id": case["id"], "expected": case["expected"], "actual": actual,
            })
    total = len(cases) if prompt_version is None else sum(
        1 for case in cases if case.get("prompt_version") == prompt_version
    )
    return SuiteResult(
        name="slot",
        total=total,
        passed=exact,
        metrics={
            "exact_match_rate": exact / total if total else 0.0,
            "field_accuracy": (
                hit_fields / total_fields if total_fields else 0.0
            ),
        },
        failures=failures,
    )


# ---------------------------------------------------------------- 差标


def _hotel(price: float, city: str) -> HotelOption:
    return HotelOption(
        option_id="h1", hotel_name="测试酒店", city=city, area="中心",
        room_type="大床房", price_per_night=price, refundable=True,
        distance_to_center_km=1.0,
    )


def _flight(price: float, cabin: str) -> FlightOption:
    return FlightOption(
        option_id="f1", airline="测试航司", flight_no="TS100",
        origin="上海", destination="北京", depart_at="2026-11-03T08:00",
        arrive_at="2026-11-03T10:00", cabin=cabin, price=price,
        refundable=True, seats_left=9,
    )


def evaluate_policy(cases: list[dict]) -> SuiteResult:
    passed = 0
    failures: list[dict] = []
    for case in cases:
        rules = PolicyRules(
            version=case.get("version", "2026.1"),
            tenant_id="demo-company",
            defaults=case.get("defaults", {}),
            rules=[Rule(**rule) for rule in case.get("rules", [])],
        )
        user = UserProfile(
            user_id="u001", tenant_id="demo-company", name="测试",
            employee_level=case["level"], department="QA", city="上海",
        )
        options = SearchResults(
            hotels=[
                _hotel(item["price"], case["destination_city"])
                for item in case.get("hotels", [])
            ],
            flights=[
                _flight(item["price"], item.get("cabin", "economy"))
                for item in case.get("flights", [])
            ],
        )
        result = check_policy(
            TripRequest(
                destination_city=case["destination_city"],
                start_date=case.get("start_date"),
            ),
            options, user, rules,
        )
        ok = (
            result.passed is case["expected_passed"]
            and result.requires_approval
            is case["expected_requires_approval"]
        )
        passed += int(ok)
        if not ok:
            failures.append({
                "id": case["id"],
                "expected": {
                    "passed": case["expected_passed"],
                    "requires_approval": case["expected_requires_approval"],
                },
                "actual": {
                    "passed": result.passed,
                    "requires_approval": result.requires_approval,
                },
            })
    total = len(cases)
    return SuiteResult(
        name="policy", total=total, passed=passed,
        metrics={"decision_accuracy": passed / total if total else 0.0},
        failures=failures,
    )


# ---------------------------------------------------------------- 检索


def _filters(case: dict) -> PolicyFilters | None:
    raw = case.get("filters")
    return PolicyFilters(**raw) if raw else None


async def _retrieval_case(case: dict, kb: dict) -> tuple[bool, dict]:
    service = KnowledgeService(
        embedder=StaticEmbedder(),
        policy_store=MemoryPolicyStore(kb),
        dense_store=StaticDenseStore(case.get("dense_ids", [])),
        policy_version="2026.1",
        seed_top_k=case.get("top_k", 8),
        graph_hops=case.get("graph_hops", 2),
        max_expanded_clauses=20,
    )
    ctx = RequestContext(
        trace_id="eval", tenant_id="demo-company", user_id="u001",
        session_id="eval",
    )
    result = await service.search_policy(
        ctx, case["query"], filters=_filters(case)
    )
    expected = case.get("expected", [])
    # MRR 看种子排序；citation 是图扩展后的完整依据集合。
    ranked = result.trace.get("seed_ids") or result.citations
    expected_rows = case.get("expected_table_rows")
    rows_correct = (
        True if expected_rows is None
        else any(table.rows == expected_rows for table in result.tables)
    )
    values = {
        "recall": recall_at_k(expected, result.citations, RECALL_K),
        "mrr": reciprocal_rank(expected, ranked),
        "precision": precision(expected, result.citations),
        "insufficient_correct": (
            result.insufficient == case.get("expected_insufficient", False)
        ),
        "table_rows_correct": rows_correct,
    }
    ok = (
        values["recall"] == 1.0
        and values["insufficient_correct"]
        and rows_correct
    )
    return ok, values


async def evaluate_retrieval(cases: list[dict],
                             kb: dict) -> SuiteResult:
    passed = 0
    failures: list[dict] = []
    recalls: list[float] = []
    mrrs: list[float] = []
    precisions: list[float] = []
    insufficient: list[float] = []
    for case in cases:
        ok, values = await _retrieval_case(case, kb)
        passed += int(ok)
        recalls.append(values["recall"])
        mrrs.append(values["mrr"])
        precisions.append(values["precision"])
        insufficient.append(float(values["insufficient_correct"]))
        if not ok:
            failures.append({"id": case["id"], **values})
    total = len(cases)
    return SuiteResult(
        name="retrieval", total=total, passed=passed,
        metrics={
            f"recall_at_{RECALL_K}": mean(recalls),
            "mrr": mean(mrrs),
            "citation_precision": mean(precisions),
            "insufficient_accuracy": mean(insufficient),
        },
        failures=failures,
    )


def load_retrieval_kb(cases_dir: Path) -> dict:
    path = cases_dir / "retrieval_kb.json"
    return load_json(path) if path.exists() else {"clauses": []}


# ---------------------------------------------------------------- 审批/revision


def evaluate_approval(cases: list[dict]) -> SuiteResult:
    passed = 0
    failures: list[dict] = []
    for case in cases:
        if case.get("kind") == "amendment":
            state = {
                "task_id": "t1", "trace_id": "trace-1",
                "tenant_id": "demo-company", "user_id": "u001",
                "session_id": "s", "status": "WAITING_HUMAN",
                "revision": case.get("revision", 0),
                "request": {"destination_city": "北京"},
                "options": {"flights": [{"option_id": "f1"}],
                            "hotels": [{"option_id": "h1"}]},
                "policy_result": {"passed": True}, "policy_refs": ["c1"],
                "approval": {"status": "pending"},
                "selected": {"flight_id": "f1"}, "confirmed": True,
                "pending_human": {"type": "clarify"},
                "pending_amendment": {"destination_city": "上海"},
                "error": {"code": "x"}, "summary": "old",
            }
            result = apply_amendment(
                state, TripRequest(**case["amended_request"])
            )
            ok = (
                result["revision"] == case["expected_revision"]
                and result["options"] == {"flights": [], "hotels": []}
                and result["policy_result"] is None
                and result["approval"] is None
                and result["confirmed"] is False
                and result["status"] == "PLANNING"
            )
            if not ok:
                failures.append({
                    "id": case["id"], "actual": {
                        "revision": result["revision"],
                        "options": result["options"],
                        "approval": result["approval"],
                        "confirmed": result["confirmed"],
                        "status": result["status"],
                    },
                })
            passed += int(ok)
            continue

        snapshot = TaskSnapshot(
            task_id="t1",
            status=TaskStatus(case.get("status", "EXECUTING")),
            revision=case.get("revision", 1),
            policy_passed=case.get("policy_passed"),
            requires_approval=case.get("requires_approval", False),
            approval_status=(
                ApprovalStatus(case["approval_status"])
                if case.get("approval_status") else None
            ),
            confirmed=case.get("confirmed", False),
        )
        result = guard_action(
            case["action"], snapshot, case.get("roles", ["employee"])
        )
        ok = result.code == case["expected_code"]
        if not ok:
            failures.append({
                "id": case["id"], "expected": case["expected_code"],
                "actual": result.code,
            })
        passed += int(ok)
    total = len(cases)
    return SuiteResult(
        name="approval", total=total, passed=passed,
        metrics={"scenario_pass_rate": passed / total if total else 0.0},
        failures=failures,
    )


# ---------------------------------------------------------------- prompt 版本


def evaluate_prompts(cases: list[dict]) -> SuiteResult:
    versions = sorted({case["prompt_version"] for case in cases})
    failures: list[dict] = []
    exact_total = 0
    metrics: dict[str, float] = {}
    for version in versions:
        version_cases = [
            case for case in cases if case["prompt_version"] == version
        ]
        hits = 0
        for case in version_cases:
            try:
                normalized = normalize_payload(
                    _load_json(case["raw_output"]),
                    today=date.fromisoformat(case["today"]),
                )
                actual = _materialize_slot(case["expected"], normalized)
                ok, _, _ = _slot_passed(case["expected"], actual)
            except Exception as exc:  # noqa: BLE001 - 解析失败计入失败
                ok = False
                actual = {"error": str(exc)}
            hits += int(ok)
            if not ok:
                failures.append({
                    "id": case["id"], "prompt_version": version,
                    "expected": case["expected"], "actual": actual,
                })
        exact_total += hits
        metrics[f"{version}_exact_match_rate"] = (
            hits / len(version_cases) if version_cases else 0.0
        )
        metrics[f"{version}_case_count"] = float(len(version_cases))
    total = len(cases)
    metrics["overall_exact_match_rate"] = (
        exact_total / total if total else 0.0
    )
    return SuiteResult(
        name="prompt", total=total, passed=exact_total,
        metrics=metrics, failures=failures,
    )


# ---------------------------------------------------------------- badcase 回放


async def evaluate_badcases(cases: list[dict], cases_dir: Path) -> SuiteResult:
    passed = 0
    failures: list[dict] = []
    kb = load_retrieval_kb(cases_dir)
    for wrapper in cases:
        suite = wrapper["suite"]
        case = wrapper["case"]
        if suite == "slot":
            result = evaluate_slots([case])
        elif suite == "policy":
            result = evaluate_policy([case])
        elif suite == "approval":
            result = evaluate_approval([case])
        elif suite == "prompt":
            result = evaluate_prompts([case])
        elif suite == "retrieval":
            result = await evaluate_retrieval([case], kb)
        else:
            result = SuiteResult(
                name="badcase", total=1, passed=0,
                failures=[{"id": wrapper["id"], "error": f"unknown suite {suite}"}],
            )
        ok = result.passed == result.total
        passed += int(ok)
        if not ok:
            failures.append({
                "id": wrapper["id"], "suite": suite,
                "source_trace_id": wrapper.get("source_trace_id"),
                "details": result.failures,
            })
    total = len(cases)
    return SuiteResult(
        name="badcase", total=total, passed=passed,
        metrics={"replay_pass_rate": passed / total if total else 1.0},
        failures=failures,
    )
