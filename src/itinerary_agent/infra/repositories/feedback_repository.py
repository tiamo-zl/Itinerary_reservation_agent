"""Badcase 回流仓储。

Feedback 只是记录问题，不改变任务状态；处理动作（reproduced/fixed）
由运营在概览页推进。
"""

from datetime import UTC, datetime

from itinerary_agent.infra.db import Database


class PostgresFeedbackRepository:
    def __init__(self, db: Database):
        self.db = db

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

    async def list_badcases(self, status: str | None,
                            limit: int) -> list[dict]:
        if status:
            rows = await self.db.fetchall(
                "SELECT * FROM badcases WHERE status = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            rows = await self.db.fetchall(
                "SELECT * FROM badcases ORDER BY created_at DESC LIMIT ?",
                (limit,),
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
