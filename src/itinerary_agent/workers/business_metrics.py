"""业务 KPI 投影：PostgreSQL -> Prometheus。

只由 worker 运行，避免 API/worker 同时写同一组 gauge 造成重复样本。
投影失败只记日志，不影响业务。
"""

import asyncio
import logging

from prometheus_client import Gauge

from itinerary_agent.domain.models import ApprovalStatus, TaskStatus

TASK_STATUS = Gauge(
    "itinerary_tasks", "Task count by status", ["status"],
)
APPROVAL_STATUS = Gauge(
    "itinerary_approvals", "Approval count by status", ["status"],
)
BADCASE_STATUS = Gauge(
    "itinerary_badcases", "Badcase count by status", ["status"],
)
TASK_COMPLETION_RATIO = Gauge(
    "itinerary_task_completion_ratio",
    "COMPLETED tasks divided by all tasks",
)
BADCASE_RATE = Gauge(
    "itinerary_badcase_rate_per_1000_tasks",
    "Open badcases per 1000 tasks",
)

logger = logging.getLogger(__name__)

BADCASE_STATUSES = ("open", "reproduced", "fixed", "closed")


class BusinessMetricsWorker:
    def __init__(self, task_repo, approval_repo, feedback_repo,
                 interval_seconds: int = 15):
        self.task_repo = task_repo
        self.approval_repo = approval_repo
        self.feedback_repo = feedback_repo
        self.interval = max(5, interval_seconds)
        self._task: asyncio.Task | None = None
        self.last_snapshot: dict = {}

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
                logger.exception("business metrics projection failed")
            await asyncio.sleep(self.interval)

    async def collect_once(self) -> dict:
        task_rows = await self.task_repo.status_counts()
        approval_rows = await self.approval_repo.status_counts()
        badcase_rows = await self.feedback_repo.status_counts()

        tasks = {row["status"]: int(row["count"]) for row in task_rows}
        approvals = {row["status"]: int(row["count"]) for row in approval_rows}
        badcases = {row["status"]: int(row["count"]) for row in badcase_rows}
        total_tasks = sum(tasks.values())

        for status in TaskStatus:
            TASK_STATUS.labels(status=status.value).set(
                tasks.get(status.value, 0)
            )
        for status in ApprovalStatus:
            APPROVAL_STATUS.labels(status=status.value).set(
                approvals.get(status.value, 0)
            )
        for status in BADCASE_STATUSES:
            BADCASE_STATUS.labels(status=status).set(badcases.get(status, 0))

        TASK_COMPLETION_RATIO.set(
            tasks.get(TaskStatus.COMPLETED.value, 0) / total_tasks
            if total_tasks else 0.0
        )
        BADCASE_RATE.set(
            badcases.get("open", 0) / total_tasks * 1000
            if total_tasks else 0.0
        )
        self.last_snapshot = {
            "tasks": tasks,
            "approvals": approvals,
            "badcases": badcases,
            "total_tasks": total_tasks,
        }
        return self.last_snapshot
