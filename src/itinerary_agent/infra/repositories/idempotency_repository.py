"""写操作幂等表仓储。"""

from itinerary_agent.infra.db import Database


class PostgresIdempotencyRepository:
    def __init__(self, db: Database):
        self.db = db

    async def get(self, key: str) -> dict | None:
        row = await self.db.fetchone(
            "SELECT result FROM idempotency WHERE key = ?", (key,)
        )
        return dict(row) if row else None

    async def put_if_absent(self, key: str, result: str,
                            created_at: str) -> int:
        """返回 1 表示写入成功，0 表示已存在（并发重试）。"""
        return await self.db.execute(
            "INSERT INTO idempotency (key, result, created_at) "
            "VALUES (?, ?, ?) ON CONFLICT (key) DO NOTHING",
            (key, result, created_at),
        )

    async def delete_older_than(self, days: int) -> int:
        """幂等键保留期；删除后旧请求重放会重新执行下单。"""
        return await self.db.execute(
            "DELETE FROM idempotency "
            "WHERE created_at < now() - (? * interval '1 day')",
            (days,),
        )
