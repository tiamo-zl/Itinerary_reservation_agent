# Runbook: incident response

## First checks

```bash
docker compose ps
curl -fsS http://127.0.0.1:8000/readyz
curl -fsS http://127.0.0.1:8001/readyz
docker compose logs --tail=100 api worker
```

JSON logs carry `trace_id`, `span_id`, `task_id`, `request_id`, `tenant_id`
and `user_id`; use them to correlate API, worker and database activity.

## Ready endpoint failures

- `database: error`: PostgreSQL is down or the pool cannot connect. Check
  `docker compose ps postgres` and `pg_isready`.
- `redis: error`: rate limiting/cache degraded. Chat fails open; approval
  decisions fail closed. Check `docker compose ps redis`.
- `checkpointer: error`: checkpoint pool failed to initialize. Inspect API
  startup logs and PostgreSQL connectivity.
- `outbox_relay: error` on the worker: the worker did not start its relay.
  Restart `worker` and inspect logs.

## Approval appears stuck

1. Check the task and approval:

   ```sql
   SELECT task_id, status, revision, lease_owner, lease_expires_at
   FROM tasks WHERE task_id = '<task>';

   SELECT approval_id, status, revision, updated_at
   FROM approvals WHERE task_id = '<task>';
   ```

2. Check the outbox:

   ```sql
   SELECT id, event_type, status, attempts, available_at, locked_by
   FROM outbox WHERE aggregate_id = '<approval>'
   ORDER BY id;
   ```

3. If `outbox.status = 'dead'`, inspect worker logs, fix the cause, then reset
   the row to `pending` with `attempts = 0`.
4. If `tasks.lease_owner` is set and `lease_expires_at` is in the future,
   another resume is in progress. Wait for expiry; do not start a second
   resume manually.

## Model degradation

- Logs include `model call failed provider=... code=...`.
- `/metrics` exposes `itinerary_model_calls_total`,
  `itinerary_model_errors_total` and cost/token counters.
- Primary failures should fall back to the configured provider. If all
  providers fail, nodes degrade deterministically (CLARIFY/default steps/
  fixed summary) instead of corrupting graph state.

## Observability stack outage

OTel, Prometheus, ELK and Langfuse are optional in P0. If they are down:

- business requests must continue
- trace and ledger projection failures are logged and swallowed
- `/metrics` stays local to the process

## SSE disconnects

`/chat` and `/tasks/{id}/resume` use SSE with `X-Accel-Buffering: no`.
If a proxy buffers, check the Nginx configuration and disable buffering for
the API route. Do not automatically replay a user turn after disconnect;
replay from the task/checkpoint state instead.
