"""模拟下单系统。

写操作必须幂等：同一 key 重复调用返回第一次的结果，并标记 replayed。
存储细节在 infra/repositories；适配器只依赖 IdempotencyStore 协议。
"""

import json
from datetime import UTC, datetime
from uuid import uuid4

from itinerary_agent.adapters.interfaces import IdempotencyStore


class MockBookingSystem:
    def __init__(self, store: IdempotencyStore):
        self.store = store

    async def book(self, kind: str, key: str, payload: dict) -> dict:
        row = await self.store.get(key)
        if row:
            return {**json.loads(row["result"]), "replayed": True}

        result = {
            "booking_id": f"{kind}-{uuid4().hex[:8]}",
            "status": "confirmed",
        }
        # 并发重试时只有一个请求能插入成功，失败方回读已有结果。
        inserted = await self.store.put_if_absent(
            key, json.dumps(result), datetime.now(UTC).isoformat()
        )
        if inserted == 0:
            row = await self.store.get(key)
            if row:
                return {**json.loads(row["result"]), "replayed": True}
        return {**result, "replayed": False}
