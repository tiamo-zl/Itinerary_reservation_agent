"""模拟下单系统。

写操作必须幂等：同一 key 重复调用返回第一次的结果，并标记 replayed。
真实系统应由业务库存方保证同样的语义。
"""

import json
from datetime import UTC, datetime
from uuid import uuid4

from itinerary_agent.infra.db import Database


class MockBookingSystem:
    def __init__(self, db: Database):
        self.db = db

    async def book(self, kind: str, key: str, payload: dict) -> dict:
        row = await self.db.fetchone(
            "SELECT result FROM idempotency WHERE key = ?", (key,)
        )
        if row:
            return {**json.loads(row["result"]), "replayed": True}

        result = {
            "booking_id": f"{kind}-{uuid4().hex[:8]}",
            "status": "confirmed",
        }
        # 并发重试时只有一个请求能插入成功，失败方回读已有结果。
        inserted = await self.db.execute(
            "INSERT INTO idempotency (key, result, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT (key) DO NOTHING",
            (key, json.dumps(result), datetime.now(UTC).isoformat()),
        )
        if inserted == 0:
            row = await self.db.fetchone(
                "SELECT result FROM idempotency WHERE key = ?", (key,)
            )
            if row:
                return {**json.loads(row["result"]), "replayed": True}
        return {**result, "replayed": False}
