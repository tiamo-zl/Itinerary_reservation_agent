"""模型调用账本仓储。"""

from uuid import uuid4

from itinerary_agent.infra.db import Database


class PostgresModelCallRepository:
    def __init__(self, db: Database):
        self.db = db

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
