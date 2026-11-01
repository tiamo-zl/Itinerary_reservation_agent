"""就绪检查用例。

Controller 只拿结果，不直接访问数据库/Redis；依赖通过端口注入。
"""

from itinerary_agent.application.ports import PingPort


class ReadinessService:
    def __init__(self, database: PingPort, redis: PingPort | None,
                 checkpointer: object | None):
        self.database = database
        self.redis = redis
        self.checkpointer = checkpointer

    async def check(self) -> dict:
        checks = {"database": "error", "redis": "error", "checkpointer": "error"}
        if await self.database.ping():
            checks["database"] = "ok"
        if self.redis is not None:
            try:
                if await self.redis.ping():
                    checks["redis"] = "ok"
            except Exception:  # noqa: BLE001 - 探针只关心可用性
                checks["redis"] = "error"
        if self.checkpointer is not None:
            checks["checkpointer"] = "ok"
        return {
            "status": "ok" if all(v == "ok" for v in checks.values()) else "degraded",
            "checks": checks,
        }
