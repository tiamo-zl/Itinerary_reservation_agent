"""HTTP 审批适配器。

审批单的读取投影仍在应用数据库；HTTP 模式下的提交/决定会同步写一份
本地投影，保证审批工作台和 outbox 恢复链路行为不变。
"""

import json
from datetime import UTC, datetime

from itinerary_agent.adapters.http.client import JsonHttpClient
from itinerary_agent.adapters.interfaces import ApprovalStore
from itinerary_agent.domain.models import ApprovalRef


class HttpApprovalSystem:
    def __init__(self, client: JsonHttpClient,
                 mirror: ApprovalStore | None = None):
        self.client = client
        self.mirror = mirror

    async def submit(self, task_id: str, revision: int,
                     payload: dict) -> ApprovalRef:
        data = await self.client.post("/approvals", {
            "task_id": task_id,
            "revision": revision,
            "payload": payload,
        })
        ref = ApprovalRef.model_validate(data)
        if self.mirror is not None:
            created_at = (
                ref.submitted_at or datetime.now(UTC)
            ).isoformat()
            await self.mirror.insert_pending(
                ref.approval_id, task_id, revision,
                json.dumps(payload, ensure_ascii=False), created_at,
            )
        return ref

    async def get(self, approval_id: str) -> ApprovalRef:
        data = await self.client.get(f"/approvals/{approval_id}")
        return ApprovalRef.model_validate(data)

    async def decide(self, approval_id: str, status: str,
                     comment: str) -> None:
        await self.client.post(
            f"/approvals/{approval_id}/decide",
            {"status": status, "comment": comment},
        )
        if self.mirror is not None:
            await self.mirror.decide(approval_id, status, comment)

    async def stop(self) -> None:
        return None
