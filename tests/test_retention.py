"""保留清理只删除过期投影/缓存，不碰业务状态。"""

from itinerary_agent.infra.repositories.idempotency_repository import (
    PostgresIdempotencyRepository,
)
from itinerary_agent.infra.repositories.llm_cache_repository import (
    PostgresLLMCache,
)
from itinerary_agent.infra.repositories.outbox_repository import (
    PostgresOutboxRepository,
)
from itinerary_agent.infra.repositories.span_repository import (
    PostgresSpanRepository,
)
from itinerary_agent.workers.retention import RetentionWorker
from tests.db_utils import make_test_settings, open_test_db


async def test_retention_deletes_only_expired_rows(tmp_path):
    db = await open_test_db()
    span_repo = PostgresSpanRepository(db)
    outbox_repo = PostgresOutboxRepository(db)
    cache_repo = PostgresLLMCache(db)
    idempotency_repo = PostgresIdempotencyRepository(db)

    await db.execute(
        "INSERT INTO spans (span_id, trace_id, name, layer, status, "
        "start_time, duration_ms, attributes) VALUES "
        "('old', 't1', 'x', 'gateway', 'ok', now() - interval '30 days', 1, '{}'),"
        "('new', 't2', 'x', 'gateway', 'ok', now(), 1, '{}')"
    )
    await db.execute(
        "INSERT INTO outbox (aggregate_type, aggregate_id, event_type, payload, "
        "status, created_at) VALUES "
        "('approval', 'a1', 'approval.decided', '{}', 'done', "
        "now() - interval '30 days'),"
        "('approval', 'a2', 'approval.decided', '{}', 'pending', "
        "now() - interval '30 days'),"
        "('approval', 'a3', 'approval.decided', '{}', 'done', now())"
    )
    await db.execute(
        "INSERT INTO llm_cache (cache_key, value, expires_at) VALUES "
        "('old', 'v', now() - interval '1 day'),"
        "('new', 'v', now() + interval '1 day')"
    )
    await db.execute(
        "INSERT INTO idempotency (key, result, created_at) VALUES "
        "('old', '{}', now() - interval '30 days'),"
        "('new', '{}', now())"
    )

    settings = make_test_settings(
        trace_retention_days=7, outbox_retention_days=7,
        idempotency_retention_days=7,
    )
    worker = RetentionWorker(
        span_repo, outbox_repo, cache_repo, idempotency_repo,
        settings, interval_seconds=3600,
    )
    deleted = await worker.run_once()

    assert deleted["spans"] == 1
    assert deleted["outbox"] == 1
    assert deleted["llm_cache"] == 1
    assert deleted["idempotency"] == 1

    assert (await db.fetchone("SELECT COUNT(*) AS c FROM spans"))["c"] == 1
    assert (await db.fetchone(
        "SELECT COUNT(*) AS c FROM outbox"
    ))["c"] == 2
    assert (await db.fetchone(
        "SELECT COUNT(*) AS c FROM llm_cache"
    ))["c"] == 1
    assert (await db.fetchone(
        "SELECT COUNT(*) AS c FROM idempotency"
    ))["c"] == 1
    await db.close()
