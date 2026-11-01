"""Outbox 仓储。

业务写与事件写在同一事务中提交；worker 用
`FOR UPDATE SKIP LOCKED` 抢占事件，保证多 worker 不重复处理。
"""

import json

from itinerary_agent.infra.db import Database


class PostgresOutboxRepository:
    def __init__(self, db: Database):
        self.db = db

    async def enqueue(self, aggregate_type: str, aggregate_id: str,
                      event_type: str, payload: dict) -> None:
        await self.db.execute(
            "INSERT INTO outbox (aggregate_type, aggregate_id, event_type, payload) "
            "VALUES (?, ?, ?, ?::jsonb)",
            (
                aggregate_type,
                aggregate_id,
                event_type,
                json.dumps(payload, ensure_ascii=False),
            ),
        )

    async def claim_batch(self, limit: int, worker_id: str,
                          lease_seconds: int) -> list[dict]:
        """抢占一批待处理事件；processing 超时的事件可被重新领取。"""
        rows = await self.db.fetchall(
            "UPDATE outbox SET status = 'processing', locked_by = ?, "
            "locked_at = now() WHERE id IN ("
            "  SELECT id FROM outbox "
            "  WHERE (status = 'pending' AND available_at <= now()) "
            "     OR (status = 'processing' "
            "         AND locked_at < now() - (? * interval '1 second')) "
            "  ORDER BY id "
            "  FOR UPDATE SKIP LOCKED "
            "  LIMIT ?"
            ") RETURNING *",
            (worker_id, lease_seconds, limit),
        )
        return [dict(row) for row in rows]

    async def mark_done(self, event_id: int) -> None:
        await self.db.execute(
            "UPDATE outbox SET status = 'done', locked_by = NULL, "
            "locked_at = NULL WHERE id = ?",
            (event_id,),
        )

    async def mark_failed(self, event_id: int, error: str,
                          max_attempts: int) -> None:
        """失败按指数退避；超过上限进入 dead，等待人工处理。"""
        row = await self.db.fetchone(
            "SELECT attempts FROM outbox WHERE id = ?", (event_id,)
        )
        attempts = (row["attempts"] if row else 0) + 1
        if attempts >= max_attempts:
            await self.db.execute(
                "UPDATE outbox SET status = 'dead', attempts = ?, "
                "locked_by = NULL, locked_at = NULL WHERE id = ?",
                (attempts, event_id),
            )
            return
        delay_seconds = min(300, 5 * (2 ** attempts))
        await self.db.execute(
            "UPDATE outbox SET status = 'pending', attempts = ?, "
            "available_at = now() + (? * interval '1 second'), "
            "locked_by = NULL, locked_at = NULL WHERE id = ?",
            (attempts, delay_seconds, event_id),
        )
