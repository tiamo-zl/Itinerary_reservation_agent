"""近线质量评估：抽样最近任务，做确定性规则检查。

不做真实模型/向量调用；只检查 Checkpoint 中的结构化状态，
结果写入 quality_findings 并投影为 Prometheus 指标。
"""

import asyncio
import hashlib
import logging

from itinerary_agent.observability.metrics import (
    QUALITY_CHECKS,
    QUALITY_PASS_RATIO,
    QUALITY_SAMPLES,
)

logger = logging.getLogger(__name__)


def _sampled(task_id: str, rate: float) -> bool:
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    digest = hashlib.sha256(task_id.encode()).digest()
    value = int.from_bytes(digest[:4], "big") / (2 ** 32)
    return value < rate


def evaluate_state(task: dict, values: dict) -> list[dict]:
    """根据任务状态返回 (check_name, status, detail) 列表。"""
    if not values:
        return [{
            "check_name": "state_available",
            "status": "fail",
            "detail": "checkpoint state is missing",
        }]

    status = values.get("status") or task.get("status") or ""
    request = values.get("request") or {}
    options = values.get("options") or {}
    selected = values.get("selected") or {}
    policy = values.get("policy_result") or {}
    approval = values.get("approval") or {}
    pending = values.get("pending_human") or {}
    findings: list[dict] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        findings.append({
            "check_name": name,
            "status": "pass" if ok else "fail",
            "detail": "" if ok else detail,
        })

    destination = request.get("destination_city")
    clarify = pending.get("type") == "clarify"
    add(
        "slot_complete",
        bool(destination) or clarify,
        "destination_city is missing",
    )

    add(
        "policy_evaluated",
        bool(policy),
        "policy_result is missing",
    )

    if status == "COMPLETED":
        need_flight = request.get("need_flight", True)
        need_hotel = request.get("need_hotel", True)
        options_ok = (
            (not need_flight or bool(options.get("flights")))
            and (not need_hotel or bool(options.get("hotels")))
        )
        add("options_available", options_ok, "completed task has no options")

        selected_ok = (
            (not need_flight or bool(selected.get("flight_id")))
            and (not need_hotel or bool(selected.get("hotel_id")))
        )
        approved = (
            bool(policy.get("passed"))
            or approval.get("status") == "approved"
        )
        add(
            "booking_consistent",
            selected_ok and approved,
            "completed task is missing selection or policy/approval proof",
        )

    add(
        "no_error",
        status != "FAILED" and not values.get("error"),
        "task has an error state",
    )
    return findings


class QualityEvalWorker:
    def __init__(self, task_repo, finding_repo, orchestrator, *,
                 interval_seconds: int = 60,
                 sample_rate: float = 0.05,
                 lookback_minutes: int = 60,
                 max_tasks: int = 100):
        self.task_repo = task_repo
        self.finding_repo = finding_repo
        self.orchestrator = orchestrator
        self.interval = max(10, interval_seconds)
        self.sample_rate = sample_rate
        self.lookback_minutes = lookback_minutes
        self.max_tasks = max_tasks
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run(self) -> None:
        while True:
            try:
                await self.collect_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("near-line quality evaluation failed")
            await asyncio.sleep(self.interval)

    async def collect_once(self) -> dict:
        tasks = await self.task_repo.list_recent(
            self.lookback_minutes, self.max_tasks
        )
        sampled = [
            task for task in tasks if _sampled(task["task_id"], self.sample_rate)
        ]
        findings: list[dict] = []
        for task in sampled:
            try:
                snapshot = await self.orchestrator.get_state_snapshot(
                    task["task_id"]
                )
                checks = evaluate_state(task, snapshot.get("values") or {})
            except Exception:
                logger.exception(
                    "quality state read failed: %s", task["task_id"]
                )
                checks = [{
                    "check_name": "state_available",
                    "status": "fail",
                    "detail": "checkpoint read failed",
                }]
            for check in checks:
                findings.append({
                    **check,
                    "task_id": task["task_id"],
                    "trace_id": task.get("trace_id"),
                    "tenant_id": task["tenant_id"],
                })

        if findings:
            await self.finding_repo.upsert_many(findings)
        if sampled:
            QUALITY_SAMPLES.inc(len(sampled))
        for finding in findings:
            QUALITY_CHECKS.labels(
                check=finding["check_name"], status=finding["status"]
            ).inc()

        by_check: dict[str, list[int]] = {}
        for finding in findings:
            bucket = by_check.setdefault(finding["check_name"], [0, 0])
            bucket[0] += 1
            bucket[1] += int(finding["status"] == "pass")
        for check, (total, passed) in by_check.items():
            QUALITY_PASS_RATIO.labels(check=check).set(passed / total)
        return {
            "sampled": len(sampled),
            "findings": len(findings),
            "checks": by_check,
        }
