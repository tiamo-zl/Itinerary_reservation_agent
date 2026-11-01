# ADR 0001: PostgreSQL as the canonical datastore

## Status

Accepted (2026-11-01)

## Context

The demo used a single SQLite file for business tables and LangGraph
checkpoints. It was easy to run offline, but could not support:

- concurrent API and worker processes
- durable leases and `FOR UPDATE SKIP LOCKED`
- operational migrations, backup and restore
- managed PostgreSQL in a production environment

## Decision

- PostgreSQL 17 is the only runtime datastore.
- Repositories use psycopg 3 with an async connection pool and explicit
  transactions.
- Schema changes are managed by Alembic; runtime code keeps raw SQL and does
  not adopt the SQLAlchemy ORM.
- LangGraph uses `AsyncPostgresSaver` with a separate connection pool.
- Historical SQLite checkpoints are not migrated. The SQLite file remains
  read-only for reference.

## Consequences

- Tests require a PostgreSQL database (`TEST_DATABASE_URL`); CI and local
  Compose provide one.
- `make db-up` exposes PostgreSQL on `127.0.0.1:55432` to avoid the local
  Langfuse stack on 5432.
- Checkpoint schema is owned by `langgraph-checkpoint-postgres`; Alembic
  must not hand-edit its tables.
