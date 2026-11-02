"""Badcase 回流仓储。

Feedback 只是记录问题，不改变任务状态；处理动作（reproduced/fixed）
由运营在概览页推进。
"""

from datetime import UTC, datetime

from itinerary_agent.infra.db import Database


def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


class PostgresFeedbackRepository:
    def __init__(self, db: Database):
        self.db = db

    async def status_counts(self) -> list[dict]:
        """按状态聚合 badcase 数，供业务指标投影。"""
        rows = await self.db.fetchall(
            "SELECT status, COUNT(*) AS count FROM badcases GROUP BY status"
        )
        return [dict(row) for row in rows]

    async def create(self, badcase: dict) -> None:
        await self.db.execute(
            "INSERT INTO badcases (badcase_id, trace_id, task_id, tenant_id, "
            "category, severity, user_input, expected, actual, comment, status, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                badcase["badcase_id"], badcase["trace_id"], badcase["task_id"],
                badcase["tenant_id"], badcase["category"], badcase["severity"],
                badcase["user_input"], badcase["expected"], badcase["actual"],
                badcase["comment"], badcase["status"],
                badcase["created_at"], badcase["updated_at"],
            ),
        )

    async def list_badcases(self, status: str | None, limit: int,
                            cursor: dict | None = None) -> list[dict]:
        conditions: list[str] = []
        params: list = []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if cursor:
            conditions.append("(created_at, badcase_id) < (?, ?)")
            params.extend([
                _as_datetime(cursor["created_at"]), cursor["badcase_id"],
            ])
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = await self.db.fetchall(
            "SELECT * FROM badcases "
            f"{where} ORDER BY created_at DESC, badcase_id DESC LIMIT ?",
            (*params, limit + 1),
        )
        return [dict(row) for row in rows]

    async def get(self, badcase_id: str) -> dict | None:
        row = await self.db.fetchone(
            "SELECT * FROM badcases WHERE badcase_id = ?", (badcase_id,)
        )
        return dict(row) if row else None

    async def update(self, badcase_id: str, changes: dict) -> None:
        assignments = ", ".join(f"{key} = ?" for key in changes)
        await self.db.execute(
            f"UPDATE badcases SET {assignments}, updated_at = ? "
            f"WHERE badcase_id = ?",
            (*changes.values(), datetime.now(UTC).isoformat(), badcase_id),
        )
