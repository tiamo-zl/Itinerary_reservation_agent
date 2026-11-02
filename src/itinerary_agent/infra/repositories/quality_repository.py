"""近线质量检查结果仓储。"""

from uuid import uuid4

from itinerary_agent.infra.db import Database


class PostgresQualityFindingRepository:
    def __init__(self, db: Database):
        self.db = db

    async def upsert_many(self, findings: list[dict]) -> None:
        for finding in findings:
            await self.db.execute(
                "INSERT INTO quality_findings "
                "(finding_id, task_id, trace_id, tenant_id, check_name, "
                "status, detail, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, now()) "
                "ON CONFLICT (task_id, check_name) DO UPDATE SET "
                "status=EXCLUDED.status, detail=EXCLUDED.detail, "
                "created_at=now()",
                (
                    uuid4().hex, finding["task_id"], finding.get("trace_id"),
                    finding["tenant_id"], finding["check_name"],
                    finding["status"], finding.get("detail", ""),
                ),
            )

    async def counts(self) -> list[dict]:
        rows = await self.db.fetchall(
            "SELECT check_name, status, COUNT(*) AS count "
            "FROM quality_findings GROUP BY check_name, status"
        )
        return [dict(row) for row in rows]

    async def list_recent(self, limit: int = 100) -> list[dict]:
        rows = await self.db.fetchall(
            "SELECT finding_id, task_id, trace_id, tenant_id, check_name, "
            "status, detail, created_at FROM quality_findings "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]
