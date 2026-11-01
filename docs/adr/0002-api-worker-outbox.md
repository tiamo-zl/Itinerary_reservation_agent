# ADR 0002: Split API and worker; drive approvals through an outbox

## Status

Accepted (2026-11-01)

## Context

Approval polling originally ran inside the API process. Resumes from a user
and from the poller could race, and a crash could leave a task stuck without a
retryable record.

## Decision

- The API process is stateless and does not start polling loops.
- A worker process uses the same image and owns approval recovery, outbox
  relay and retention.
- Approval decisions update the approval row and insert an outbox event in one
  PostgreSQL transaction.
- The worker claims events with `FOR UPDATE SKIP LOCKED`, retries with
  exponential backoff and moves exhausted events to `dead`.
- Task resumes acquire a database lease (`lease_owner`, `lease_expires_at`);
  only one process may resume a task at a time.
- A temporary polling fallback is enabled only when
  `MOCK_APPROVAL_AUTO_APPROVE=true`, because mock auto-approval does not emit
  an outbox event.

## Consequences

- Deployments must run both `api` and `worker`; `docker compose --profile core`
  does this.
- Delivery is at-least-once. Idempotency comes from task status checks,
  leases and booking idempotency keys.
- A worker killed mid-resume leaves a lease; it expires and another worker
  retries.
