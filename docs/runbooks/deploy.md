# Runbook: local Compose deployment

## Prerequisites

- Docker with the `postgres:17`, `redis:7`, `node:24-alpine` and
  `nginx:alpine` images available (or network access to pull them).
- `uv` installed; dependencies synced by the user (`uv sync --dev`).
- `.env` copied from `.env.example`.

## Start

```bash
docker compose --profile core up -d --build
docker compose ps
```

The `migrate` service runs `alembic upgrade head` before API and worker start.

Expected endpoints:

- Web: http://127.0.0.1:8080
- API: http://127.0.0.1:8000
- Worker: http://127.0.0.1:8001
- PostgreSQL: 127.0.0.1:55432
- Redis: 127.0.0.1:56379

## Verify

```bash
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS http://127.0.0.1:8000/readyz
curl -fsS http://127.0.0.1:8001/readyz
curl -fsS http://127.0.0.1:8000/metrics | head
```

`/readyz` must report `database`, `redis` and `checkpointer` as `ok`; the
worker additionally checks `outbox_relay` and `retention`.

Retention defaults (configurable through `.env`):

| Setting | Default | Deletes |
|---|---|---|
| `TRACE_RETENTION_DAYS` | 7 | span projection |
| `OUTBOX_RETENTION_DAYS` | 30 | `done`/`dead` outbox rows |
| `IDEMPOTENCY_RETENTION_DAYS` | 7 | idempotency keys |
| `RETENTION_INTERVAL_SECONDS` | 3600 | run interval |

Set `RETENTION_ENABLED=false` to disable the worker.

## Update

```bash
git pull
docker compose --profile core build api web
docker compose --profile core up -d
```

Migrations run automatically; run `make migrate` manually if the `migrate`
service was skipped.

## Rollback

1. Check out the previous known-good revision.
2. Rebuild images.
3. `docker compose --profile core up -d`.
4. If a migration was destructive, restore the pre-deploy backup first
   (see `database.md`). Migrations are forward-only; do not edit Alembic
   history in place.

## Stop

```bash
docker compose --profile core down
```

Data remains in the `pgdata` and `redisdata` volumes. Use `down -v` only when
you intentionally want to delete local data.
