"""在线 LLM-as-judge：抽样已完成任务做主观质量评审。

只在 MODEL_MODE=live 且 JUDGE_ENABLED=true 时启动；所有模型调用仍走
model_gateway，便于缓存、成本、熔断和账本统一治理。
"""

import asyncio
import hashlib
import json
import logging

from itinerary_agent.domain.models import CallContext, ModelTier
from itinerary_agent.model_gateway.prompts import default_prompt_registry
from itinerary_agent.observability.metrics import (
    JUDGE_ERRORS,
    JUDGE_PASS_RATIO,
    JUDGE_RESULTS,
    JUDGE_SCORE,
)
from itinerary_agent.security.pii import scrub_obj

logger = logging.getLogger(__name__)

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 0, "maximum": 5},
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
        "reason": {"type": "string"},
    },
    "required": ["score", "verdict", "reason"],
}


def _sampled(task_id: str, rate: float) -> bool:
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    digest = hashlib.sha256(task_id.encode()).digest()
    return int.from_bytes(digest[:4], "big") / (2 ** 32) < rate


def build_judge_payload(task: dict, values: dict) -> dict:
    request = values.get("request") or {}
    options = values.get("options") or {}
    policy = values.get("policy_result") or {}
    approval = values.get("approval") or {}
    payload = {
        "task_status": values.get("status") or task.get("status"),
        "request": {
            key: request.get(key)
            for key in (
                "destination_city", "origin_city", "start_date",
                "end_date", "budget_limit", "hotel_area", "cabin",
                "need_flight", "need_hotel", "purpose",
            )
        },
        "selected": values.get("selected") or {},
        "options": {
            "flights": [
                {
                    "airline": item.get("airline"),
                    "price": item.get("price"),
                    "cabin": item.get("cabin"),
                }
                for item in (options.get("flights") or [])
            ],
            "hotels": [
                {
                    "hotel_name": item.get("hotel_name"),
                    "price_per_night": item.get("price_per_night"),
                }
                for item in (options.get("hotels") or [])
            ],
        },
        "policy": {
            "passed": policy.get("passed"),
            "requires_approval": policy.get("requires_approval"),
            "violations": [
                item.get("message") for item in (policy.get("violations") or [])
            ],
        },
        "approval": {"status": approval.get("status")},
        "summary": values.get("summary") or "",
    }
    return scrub_obj(payload)


class LLMJudgeWorker:
    def __init__(self, task_repo, judge_repo, orchestrator, model, *,
                 prompt_version: str = "v1",
                 interval_seconds: int = 120,
                 sample_rate: float = 0.01,
                 lookback_minutes: int = 120,
                 max_tasks: int = 50):
        self.task_repo = task_repo
        self.judge_repo = judge_repo
        self.orchestrator = orchestrator
        self.model = model
        self.prompt_version = prompt_version
        self.interval = max(30, interval_seconds)
        self.sample_rate = sample_rate
        self.lookback_minutes = lookback_minutes
        self.max_tasks = max_tasks
        self.prompts = default_prompt_registry()
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
                logger.exception("LLM judge batch failed")
            await asyncio.sleep(self.interval)

    async def collect_once(self, tasks: list[dict] | None = None) -> dict:
        if tasks is None:
            tasks = await self.task_repo.list_recent(
                self.lookback_minutes, self.max_tasks
            )
        results = {"sampled": 0, "judged": 0, "pass": 0, "fail": 0}
        for task in tasks:
            if not _sampled(task["task_id"], self.sample_rate):
                continue
            results["sampled"] += 1
            if await self.judge_repo.exists(
                task["task_id"], self.prompt_version
            ):
                continue
            try:
                snapshot = await self.orchestrator.get_state_snapshot(
                    task["task_id"]
                )
                values = snapshot.get("values") or {}
                if values.get("status") != "COMPLETED":
                    continue
                payload = build_judge_payload(task, values)
                template = self.prompts.get("judge", self.prompt_version)
                ctx = CallContext(
                    trace_id=task.get("trace_id") or "judge",
                    tenant_id=task["tenant_id"],
                    task_id=task["task_id"],
                    purpose="judge",
                    prompt_version=template.version,
                )
                messages = [
                    {"role": "system", "content": template.text},
                    {"role": "user", "content": json.dumps(
                        payload, ensure_ascii=False
                    )},
                ]
                completion = await self.model.complete(
                    ctx, messages, ModelTier.STANDARD,
                    response_schema=JUDGE_SCHEMA,
                )
                data = json.loads(completion.text)
                score = int(data["score"])
                verdict = data["verdict"]
                if verdict not in {"pass", "fail"} or not 0 <= score <= 5:
                    raise ValueError("judge returned invalid verdict/score")
            except Exception as exc:  # noqa: BLE001 - 单条评审失败不阻塞批次
                JUDGE_ERRORS.labels(code=type(exc).__name__).inc()
                logger.warning(
                    "judge failed task=%s: %s", task["task_id"], exc
                )
                continue

            await self.judge_repo.create({
                "task_id": task["task_id"],
                "trace_id": task.get("trace_id"),
                "tenant_id": task["tenant_id"],
                "prompt_version": template.version,
                "model": completion.model,
                "provider": completion.provider,
                "score": score,
                "verdict": verdict,
                "reason": str(data.get("reason", ""))[:500],
            })
            JUDGE_RESULTS.labels(verdict=verdict).inc()
            JUDGE_SCORE.observe(score)
            results["judged"] += 1
            results[verdict] += 1

        if results["judged"]:
            JUDGE_PASS_RATIO.set(results["pass"] / results["judged"])
        return results
