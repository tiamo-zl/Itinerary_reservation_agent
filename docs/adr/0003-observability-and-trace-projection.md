# ADR 0003: OTel instrumentation plus a PostgreSQL trace projection

## Status

Accepted (2026-11-01)

## Context

The custom `TraceRecorder` wrote spans directly to SQLite and powered the Vue
console. Production needs standard instrumentation, external traces, metrics,
logs and a business view that external tools cannot provide.

## Decision

- OpenTelemetry is the instrumentation standard. `OTEL_ENABLED=true` enables
  the SDK, OTLP exporter, sampling, and FastAPI/httpx/psycopg/Redis
  auto-instrumentation. It is off by default so offline startup does not
  require a Collector.
- `TraceRecorder` keeps its existing facade and creates OTel spans when
  enabled, while writing the same span projection to PostgreSQL.
- The PostgreSQL projection is canonical for the Vue console: flow graph,
  approvals, checkpoint history, task aggregation and badcases.
- Prometheus metrics are exposed at `/metrics` on both API and worker.
- Logs are JSON and carry `trace_id`, `span_id`, `task_id`, `request_id`,
  `tenant_id` and `user_id`; sensitive fields and phone/ID patterns are
  redacted.
- Tracing backends in P1: OTel Collector fans out to SkyWalking and Langfuse;
  Prometheus/Grafana handles metrics; ELK handles logs.

## Consequences

- P0 emits OTel spans but does not yet guarantee identical trace IDs between
  the PostgreSQL projection and SkyWalking. P1 aligns IDs and configures the
  Collector fan-out.
- Observability outages must not fail business requests. Trace and ledger
  writes already swallow failures and log them.
- High-cardinality identifiers stay in span attributes, not metric labels.
