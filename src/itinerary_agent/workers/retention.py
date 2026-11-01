"""保留清理 worker。

只处理可再生成的投影/缓存数据：trace span、过期缓存、已结束的 outbox
和过期幂等键。所有删除都按创建时间阈值执行，避免一次误删全表。
"""

import asyncio
import logging

from itinerary_agent.observability.metrics import RETENTION_DELETED

logger = logging.getLogger(__name__)


class RetentionWorker:
    def __init__(self, span_repo, outbox_repo, cache_repo, idempotency_repo,
                 settings, interval_seconds: int):
        self.span_repo = span_repo
        self.outbox_repo = outbox_repo
        self.cache_repo = cache_repo
        self.idempotency_repo = idempotency_repo
        self.settings = settings
        self.interval = max(60, interval_seconds)
        self._task: asyncio.Task | None = None
        self.last_result: dict[str, int] = {}

    def start(self) -> None:
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run(self) -> None:
        while True:
            try:
                self.last_result = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("retention run failed")
            await asyncio.sleep(self.interval)

    async def run_once(self) -> dict[str, int]:
        """执行一轮清理；返回每张表的删除行数。"""
        deleted = {
            "spans": await self.span_repo.delete_older_than(
                self.settings.trace_retention_days
            ),
            "outbox": await self.outbox_repo.delete_finished_older_than(
                self.settings.outbox_retention_days
            ),
            "idempotency": await self.idempotency_repo.delete_older_than(
                self.settings.idempotency_retention_days
            ),
        }
        if self.cache_repo is not None:
            deleted["llm_cache"] = await self.cache_repo.purge_expired()
        for table, count in deleted.items():
            if count:
                RETENTION_DELETED.labels(table=table).inc(count)
        logger.info("retention deleted rows: %s", deleted)
        return deleted
