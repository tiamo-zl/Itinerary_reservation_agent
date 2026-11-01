# Runbook: PostgreSQL migrations and backups

## Connection

- Development: `postgresql://itinerary:itinerary_dev@127.0.0.1:55432/itinerary`
- Tests: same host, database `itinerary_test`
- Compose service name: `postgres`

## Migrations

```bash
make migrate                 # alembic upgrade head
make revision m="add index"  # create a new revision
uv run alembic current
```

Rules:

- The LangGraph checkpoint tables are owned by
  `langgraph-checkpoint-postgres`. Do not hand-edit them with Alembic.
- Additive changes are preferred; destructive changes require a backup and a
  documented rollback plan.
- Historical SQLite checkpoints are not migrated.

## Backup

```bash
docker compose exec -T postgres \
  pg_dump -U itinerary -Fc itinerary > data/itinerary-$(date +%F).dump
```

Store backups outside the repository (`data/` is gitignored).

## Restore

1. Stop API and worker to prevent writes:

   ```bash
   docker compose stop api worker
   ```

2. Recreate the database (destructive):

   ```bash
   docker compose exec -T postgres psql -U itinerary -d postgres \
     -c "DROP DATABASE itinerary WITH (FORCE);"
   docker compose exec -T postgres psql -U itinerary -d postgres \
     -c "CREATE DATABASE itinerary;"
   ```

3. Restore:

   ```bash
   docker compose exec -T postgres \
     pg_restore -U itinerary -d itinerary --clean --if-exists < backup.dump
   ```

4. Start services and verify `/readyz`.

## Test database

`make db-up` creates `itinerary_test` on first initialization. Tests truncate
business tables before each case; checkpoint tables are left in place and
isolated by task ID.
