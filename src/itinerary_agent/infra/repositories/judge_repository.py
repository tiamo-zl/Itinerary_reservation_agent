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

    async def list_recent(self, limit: int = 100,
                          review_status: str | None = None,
                          verdict: str | None = None) -> list[dict]:
        conditions: list[str] = []
        params: list = []
        if review_status:
            conditions.append("review_status = ?")
            params.append(review_status)
        if verdict:
            conditions.append("verdict = ?")
            params.append(verdict)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = await self.db.fetchall(
            "SELECT judge_id, task_id, trace_id, tenant_id, prompt_version, "
            "model, provider, score, verdict, reason, created_at, "
            "review_status, human_score, human_verdict, reviewer, "
            "review_comment, reviewed_at "
            f"FROM judge_results {where} "
            "ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        )
        return [dict(row) for row in rows]

    async def get(self, judge_id: str) -> dict | None:
        row = await self.db.fetchone(
            "SELECT judge_id, task_id, trace_id, tenant_id, prompt_version, "
            "model, provider, score, verdict, reason, created_at, "
            "review_status, human_score, human_verdict, reviewer, "
            "review_comment, reviewed_at FROM judge_results "
            "WHERE judge_id = ?",
            (judge_id,),
        )
        return dict(row) if row else None

    async def review(self, judge_id: str, human_score: int,
                     human_verdict: str, reviewer: str,
                     comment: str = "") -> None:
        await self.db.execute(
            "UPDATE judge_results SET review_status = 'reviewed', "
            "human_score = ?, human_verdict = ?, reviewer = ?, "
            "review_comment = ?, reviewed_at = now() "
            "WHERE judge_id = ?",
            (human_score, human_verdict, reviewer, comment, judge_id),
        )

    async def counts(self) -> list[dict]:
        rows = await self.db.fetchall(
            "SELECT verdict, COUNT(*) AS count, AVG(score) AS avg_score "
            "FROM judge_results GROUP BY verdict"
        )
        return [dict(row) for row in rows]

    async def review_counts(self) -> list[dict]:
        rows = await self.db.fetchall(
            "SELECT review_status, COUNT(*) AS count "
            "FROM judge_results GROUP BY review_status"
        )
        return [dict(row) for row in rows]

    async def report_summary(self) -> dict:
        """工具报告用的聚合指标。"""
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS total, "
            "COUNT(*) FILTER (WHERE verdict = 'pass') AS pass, "
            "COUNT(*) FILTER (WHERE verdict = 'fail') AS fail, "
            "COUNT(*) FILTER (WHERE review_status = 'pending') AS pending, "
            "COUNT(*) FILTER (WHERE review_status = 'reviewed') AS reviewed, "
            "AVG(score) AS avg_score, MAX(created_at) AS latest_at "
            "FROM judge_results"
        )
        return dict(row) if row else {}
