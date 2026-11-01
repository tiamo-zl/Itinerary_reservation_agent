"""Trace span 投影仓储。"""

import json

from itinerary_agent.infra.db import Database


class PostgresSpanRepository:
    def __init__(self, db: Database):
        self.db = db

    async def write_span(self, span_id: str, trace_id: str,
                         parent_id: str | None, name: str, layer: str,
                         status: str, started_at, duration_ms: float,
                         attributes: dict) -> None:
        await self.db.execute(
            "INSERT INTO spans (span_id, trace_id, parent_span_id, name, layer, "
            "status, start_time, duration_ms, attributes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                span_id, trace_id, parent_id, name, layer, status,
                started_at, duration_ms,
                json.dumps(attributes, ensure_ascii=False, default=str),
            ),
        )

    async def delete_older_than(self, days: int) -> int:
        """保留策略：删除超过保留期的 span 投影。"""
        return await self.db.execute(
            "DELETE FROM spans "
            "WHERE start_time < now() - (? * interval '1 day')",
            (days,),
        )
