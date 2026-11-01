"""模拟审批系统。

真实环境会接企业 BPM/审批平台；这里用 SQLite + 延时自动通过模拟。
同一 task_id + revision 的重复提交是幂等的，避免 resume 时重复建单。
"""

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

from itinerary_agent.domain.models import ApprovalRef
from itinerary_agent.infra.db import Database


class MockApprovalSystem:
    def __init__(self, db: Database, auto_approve_delay: float = 5.0,
                 auto_approve: bool = False):
        self.db = db
        self.delay = auto_approve_delay
        self.auto_approve = auto_approve
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
        inserted = await self.db.execute(
            "INSERT INTO approvals (approval_id, task_id, revision, status, comment, "
            "payload, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (task_id, revision) DO NOTHING",
            (
                approval_id, task_id, revision, "pending", None,
                json.dumps(payload, ensure_ascii=False), now, now,
            ),
        )
        if inserted == 0:
            # 并发提交同一 task/revision 时复用已存在的审批单。
            existing = await self.db.fetchone(
                "SELECT approval_id FROM approvals WHERE task_id = ? AND revision = ?",
                (task_id, revision),
            )
            if existing:
                return await self.get(existing["approval_id"])

        # 默认不自动通过，让审批页展示待办；需要演示自动通过时显式开启。
        if self.auto_approve and self.delay < 900:
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
        created_at = row["created_at"]
        if not isinstance(created_at, datetime):
            created_at = datetime.fromisoformat(created_at)
        return ApprovalRef(
            approval_id=row["approval_id"],
            status=row["status"],
            comment=row["comment"],
            submitted_at=created_at,
        )
