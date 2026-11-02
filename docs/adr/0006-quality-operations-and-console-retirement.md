# ADR 0006: Split quality operations and retire the self-built observability console

## Status

Accepted (2026-11-01); console frozen as demo (2026-11-02); retirement deferred.

## Context

The Vue console at `web/` renders a PostgreSQL span projection:

- `/overview` aggregates spans, layers, LLM cost, approvals, tasks and badcases;
- `/trace/{id}` shows the call tree, checkpoint history, transcript and approvals;
- `/flow/{id}` renders an orchestration timeline derived from node spans.

This is a business trace projection with a UI, not a platform observability
system. It lacks sampling, retention tiers, a query language, alerting, RBAC,
multi-service correlation and cost governance. It also mixes three concerns
that have different owners and lifecycles:

1. platform observability (metrics, logs, traces);
2. business state (tasks, approvals, checkpoints, conversations);
3. quality operations (eval datasets, badcases, acceptance evidence).

P1 adds a five-piece stack (Prometheus/Grafana, ELK, OTel Collector, SkyWalking,
Langfuse) and an offline evaluation harness. At that point the console becomes
a temporary convenience rather than a source of truth.

Known blockers for retiring the console:

- SkyWalking 11.0.0 receives OTLP/Zipkin spans into `sw_zipkin_span-*` but does
  not build `sw_segment`, so the service catalog is empty.
- Elasticsearch stores application JSON inside `body.text`; `trace_id`,
  `task_id` and `request_id` are not structured fields.
- Business KPIs (task status, approval latency, recovery success, open
  badcases) exist only in PostgreSQL and are rendered by the console.
- API responses return `X-Request-ID` but not `X-Trace-Id`, so users and
  support cannot hand over a trace link.

## Decision

### 1. Split responsibilities

| Concern | System of record | Interface |
|---|---|---|
| Platform observability | Prometheus/Grafana, ELK, OTel trace backend | Dashboards, queries, alerts |
| Business state | PostgreSQL plus product backoffice | Admin APIs with RBAC |
| Quality operations | Eval datasets plus ticket system | CI gate, ticket workflow |

The `spans` projection, `badcases` table and their APIs remain; only the
self-built observability **views** are retired.

### 2. Retire the console views after replacement

`/overview`, `/trace/{id}` and `/flow/{id}` are retired only when all exit
criteria are met:

- a full `/chat` call tree is visible in an external trace backend;
- Kibana can filter by structured `trace_id` and `task_id`;
- the three Grafana dashboards cover service health, agent quality and the
  business funnel;
- product backoffice covers task, approval, checkpoint and transcript views;
- badcase intake and status live in the ticket system.

### 3. Make the trace backend usable

Either fix SkyWalking's OTLP/Zipkin ingestion so segments and service catalogs
are built, or replace it with a trace backend that stores complete OTLP spans
(for example Grafana Tempo or Jaeger). Langfuse is not a substitute: it only
receives spans carrying `task_id` and is LLM-oriented.

### 4. Observability is evidence, not a page

- Define SLOs for availability, latency and business completion; alert on
  multi-window burn rate in addition to existing threshold rules.
- Emit business KPIs as metrics (or expose them through a read-only Grafana
  PostgreSQL data source).
- Structure logs at the Collector (`json_parser`) so identifiers are indexed.
- Return `X-Trace-Id` in API responses and use `trace_id` as the join key
  across logs, metrics, tickets, eval cases and alerts.
- Ship dashboards as code through Grafana provisioning.

### 5. Quality operations are tiered and versioned

- Offline golden set remains the CI gate; add near-line replay and sampled
  online evaluation as separate tiers.
- Every eval result records `dataset_version`, `prompt_version`, `model` and
  `rules_version`.
- Datasets are split into `golden`, `regression` and `holdout`; badcase cases
  carry `source_trace_id`.
- The ticket system is the system of record for badcases. A badcase cannot be
  closed without a regression case in the dataset.
- Acceptance is an evidence bundle (CI artifacts, dashboard and query links,
  trace IDs, eval report, drill log), not a manual page walk-through.

### 6. Migrate in three stages

| Stage | Actions | Exit criteria |
|---|---|---|
| Dual-run | Keep the console; fix trace backend; structure logs; export business metrics | External trace tree and structured log queries work |
| Cut read paths | Move business views to backoffice; badcases to tickets; complete three dashboards | No role needs the console views for daily work |
| Retire views | Remove observability views; keep projection tables and APIs | Observability, eval, badcase and acceptance are independently supported |

### 7. Freeze before retirement (2026-11-02)

Actual retirement is deferred. The console is frozen as a demo:

- no new console features or schema changes made only for it;
- it is not a source of truth for observability, business state or quality;
- runbooks, alerts, acceptance and badcase workflows must not require it;
- production observability stays in Tempo / Grafana / Kibana;
- it remains bound to localhost for the local demo; any non-local deployment
  needs authentication or gateway protection;
- the projection tables and query APIs remain for now.

The exit criteria in section 2 are unchanged. When the product backoffice and
ticket integration exist, the observability views can be removed and this ADR
moves to "Implemented".

## Consequences

- Operating observability becomes a platform responsibility with its own
  retention, access control and cost.
- Debugging depends on the external trace backend; its availability and
  correctness become part of the on-call surface.
- A product backoffice and RBAC model are required for business state.
- Badcase throughput depends on ticket workflow discipline; closing a ticket
  requires dataset changes to be verified by CI.
- Business KPI export must be maintained as new task states are added.
- The project no longer needs to build query, retention and alerting features
  into application code.

## Alternatives considered

- **Keep the console as the primary observability surface.** Rejected: it
  cannot provide sampling, retention, querying, alerting, RBAC or
  cross-service correlation at production scale.
- **Move all trace inspection to Langfuse.** Rejected: Langfuse only sees
  `task_id` spans and is not a general trace store.
- **Keep business views in the console.** Rejected: business state needs RBAC,
  audit and product workflow, which do not belong in an observability tool.
