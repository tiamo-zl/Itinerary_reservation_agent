"""Outbox relay：把业务事件转成后台动作。

审批决定与 outbox 行在同一事务提交；worker 领取事件后恢复任务。
事件至少投递一次，靠任务状态检查保证不会重复恢复。
"""

import asyncio
import json
import logging
from uuid import uuid4

from itinerary_agent.application.ports import (
    OrchestrationPort,
    OutboxRepositoryPort,
    TaskRepositoryPort,
)
from itinerary_agent.domain.models import ApprovalStatus, Decision, RequestContext
from itinerary_agent.observability.metrics import OUTBOX_EVENTS

logger = logging.getLogger(__name__)


class OutboxRelay:
    def __init__(self, outbox: OutboxRepositoryPort,
                 task_repo: TaskRepositoryPort,
                 orchestrator: OrchestrationPort,
                 interval: float = 1.0,
                 max_attempts: int = 5,
                 lease_seconds: int = 60):
        self.outbox = outbox
        self.task_repo = task_repo
        self.orchestrator = orchestrator
        self.interval = interval
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds
        self.worker_id = f"worker-{uuid4().hex[:8]}"
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
            events = await self.outbox.claim_batch(
                limit=10,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            for event in events:
                try:
                    await self._handle(event)
                    await self.outbox.mark_done(event["id"])
                    OUTBOX_EVENTS.labels(status="done").inc()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("outbox event failed: %s", event.get("id"))
                    await self.outbox.mark_failed(
                        event["id"], str(exc), self.max_attempts
                    )
                    OUTBOX_EVENTS.labels(status="failed").inc()
            if not events:
                await asyncio.sleep(self.interval)

    async def _handle(self, event: dict) -> None:
        payload = event.get("payload") or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        if event.get("event_type") != "approval.decided":
            return

        task_id = payload["task_id"]
        task = await self.task_repo.get(task_id)
        # 幂等保护：任务已恢复/结束，或已不在等待审批，直接视为处理完成。
        if task is None or task["status"] != "WAITING_APPROVAL":
            return

        ctx = RequestContext(
            trace_id=payload.get("trace_id") or f"approval-{task_id}",
            tenant_id=task["tenant_id"],
            user_id=task["user_id"],
            session_id="approval",
        )
        decision = Decision(
            action="continue",
            approval_status=ApprovalStatus(payload["status"]),
            comment=payload.get("comment") or "",
        )
        busy = False
        async for resume_event in self.orchestrator.resume(
            ctx, task_id, decision
        ):
            if (
                resume_event.type == "error"
                and resume_event.data.get("code") == "TASK_BUSY"
            ):
                busy = True
        if busy:
            # 让 outbox 事件进入重试；下一轮若任务已被别人完成会直接跳过。
            raise RuntimeError("task is being resumed by another process")
