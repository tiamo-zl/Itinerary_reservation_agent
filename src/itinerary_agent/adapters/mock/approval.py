"""模拟审批系统。

真实环境会接企业 BPM/审批平台；这里用 SQLite + 延时自动通过模拟。
同一 task_id + revision 的重复提交是幂等的，避免 resume 时重复建单。
"""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from itinerary_agent.domain.models import ApprovalRef
from itinerary_agent.infra.db import Database


class MockApprovalSystem:
    def __init__(self, db: Database, auto_approve_delay: float = 5.0):
        self.db = db
        self.delay = auto_approve_delay
        self._tasks: set[asyncio.Task] = set()

    async def submit(self, task_id: str, revision: int, payload: dict) -> ApprovalRef:
        existing = await self.db.fetchone(
            "SELECT approval_id FROM approvals WHERE task_id = ? AND revision = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (task_id, revision),
        )
        if existing:
            return await self.get(existing["approval_id"])

        approval_id = uuid4().hex
        now = datetime.now(UTC).isoformat()
        await self.db.execute(
            "INSERT INTO approvals (approval_id, task_id, revision, status, comment, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (approval_id, task_id, revision, "pending", None, now, now),
        )
        # demo 默认自动通过，便于演示主链路；手动审批用 decide 模拟驳回。
        if self.delay < 900:
            timer = asyncio.create_task(self._auto_approve(approval_id))
            self._tasks.add(timer)
            timer.add_done_callback(self._tasks.discard)
        return await self.get(approval_id)

    async def _auto_approve(self, approval_id: str) -> None:
        await asyncio.sleep(self.delay)
        await self.decide(approval_id, "approved", "自动通过")

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()

    async def decide(self, approval_id: str, status: str, comment: str) -> None:
        await self.db.execute(
            "UPDATE approvals SET status = ?, comment = ?, updated_at = ? "
            "WHERE approval_id = ?",
            (status, comment, datetime.now(UTC).isoformat(), approval_id),
        )

    async def get(self, approval_id: str) -> ApprovalRef:
        row = await self.db.fetchone(
            "SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)
        )
        return ApprovalRef(
            approval_id=row["approval_id"],
            status=row["status"],
            comment=row["comment"],
            submitted_at=datetime.fromisoformat(row["created_at"]),
        )
