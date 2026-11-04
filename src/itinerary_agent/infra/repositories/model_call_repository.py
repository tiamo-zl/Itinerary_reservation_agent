"""模型调用账本仓储。"""

from uuid import uuid4

from itinerary_agent.infra.db import Database


class PostgresModelCallRepository:
    def __init__(self, db: Database):
        self.db = db

    async def purpose_summary(self, purpose: str) -> dict:
        """按用途聚合调用量、失败、token、成本和延迟。"""
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS calls, "
            "COUNT(*) FILTER (WHERE status = 'ok') AS ok, "
            "COUNT(*) FILTER (WHERE status IS NOT NULL "
            "                  AND status <> 'ok') AS errors, "
            "COALESCE(SUM(prompt_tokens + completion_tokens), 0) AS tokens, "
            "COALESCE(SUM(cost_usd), 0) AS cost_usd, "
            "COUNT(*) FILTER (WHERE cache_hit) AS cache_hits, "
            "COALESCE(AVG(duration_ms), 0) AS avg_ms "
            "FROM llm_calls WHERE purpose = ?",
            (purpose,),
        )
        return dict(row) if row else {}

    async def task_usage(self, task_id: str) -> dict:
        """任务累计 token/成本，用于预算闸门。"""
        row = await self.db.fetchone(
            "SELECT COALESCE(SUM(prompt_tokens + completion_tokens), 0) "
            "AS tokens, COALESCE(SUM(cost_usd), 0) AS cost_usd "
            "FROM llm_calls WHERE task_id = ?",
            (task_id,),
        )
        return dict(row) if row else {"tokens": 0, "cost_usd": 0.0}

    async def record(self, *, trace_id: str, task_id: str | None,
                     tenant_id: str, purpose: str, model: str,
                     prompt_tokens: int, completion_tokens: int,
                     cost_usd: float, duration_ms: float, provider: str,
                     prompt_version: str, status: str,
                     error_code: str | None = None,
                     cache_hit: bool = False,
                     fallback_from: str | None = None,
                     attempt: int = 1) -> None:
        await self.db.execute(
            "INSERT INTO llm_calls (call_id, trace_id, task_id, tenant_id, "
            "purpose, model, prompt_tokens, completion_tokens, cost_usd, "
            "duration_ms, created_at, provider, prompt_version, status, "
            "error_code, cache_hit, fallback_from, attempt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now(), ?, ?, ?, ?, ?, ?, ?)",
            (
                uuid4().hex, trace_id, task_id, tenant_id, purpose, model,
                prompt_tokens, completion_tokens, cost_usd, duration_ms,
                provider, prompt_version, status, error_code, cache_hit,
                fallback_from, attempt,
            ),
        )
