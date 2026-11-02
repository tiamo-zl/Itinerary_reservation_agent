"""LLM-as-judge 结果仓储。"""

from uuid import uuid4

from itinerary_agent.infra.db import Database


class PostgresJudgeRepository:
    def __init__(self, db: Database):
        self.db = db

    async def exists(self, task_id: str, prompt_version: str) -> bool:
        row = await self.db.fetchone(
            "SELECT 1 AS ok FROM judge_results "
            "WHERE task_id = ? AND prompt_version = ?",
            (task_id, prompt_version),
        )
        return row is not None

    async def create(self, result: dict) -> None:
        await self.db.execute(
            "INSERT INTO judge_results "
            "(judge_id, task_id, trace_id, tenant_id, prompt_version, model, "
            "provider, score, verdict, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now()) "
            "ON CONFLICT (task_id, prompt_version) DO NOTHING",
            (
                uuid4().hex, result["task_id"], result.get("trace_id"),
                result["tenant_id"], result["prompt_version"],
                result["model"], result.get("provider"), result["score"],
                result["verdict"], result.get("reason", ""),
            ),
        )

    async def list_recent(self, limit: int = 100) -> list[dict]:
        rows = await self.db.fetchall(
            "SELECT judge_id, task_id, trace_id, tenant_id, prompt_version, "
            "model, provider, score, verdict, reason, created_at "
            "FROM judge_results ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]

    async def counts(self) -> list[dict]:
        rows = await self.db.fetchall(
            "SELECT verdict, COUNT(*) AS count, AVG(score) AS avg_score "
            "FROM judge_results GROUP BY verdict"
        )
        return [dict(row) for row in rows]
