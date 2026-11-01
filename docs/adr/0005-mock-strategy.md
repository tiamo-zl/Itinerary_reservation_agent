# ADR 0005: In-process mocks in P0, HTTP mock services in P1

## Status

Accepted (2026-11-01)

## Context

External systems are intentionally mocked. Keeping mocks in-process is fast
and offline, but does not exercise network timeouts, retries, contract drift
or circuit breaking.

## Decision

- P0 keeps in-process mock adapters behind `adapters/interfaces.py` protocols.
  They are wired only by `infra/container.py`.
- P1 adds standalone `mock_services/` HTTP services and real HTTP adapters
  with timeouts, retries, circuit breakers, trace propagation and contract
  tests. `ADAPTER_MODE=http` selects them; `inprocess` remains the offline
  default.
- Mock approval and booking state lives in dedicated repository tables, not
  shared with business tables in a real deployment.

## Consequences

- P0 tests remain fast and deterministic.
- P1 contract tests must run against the mock services and cover 404/429/500,
  timeout and idempotent replay.
- Replacing a mock with a real adapter changes wiring, not orchestration code.
