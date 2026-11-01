# ADR 0004: Mock, JWT and OIDC authentication

## Status

Accepted (2026-11-01)

## Context

The demo trusted `X-Mock-User`, which is forgeable. External identity systems
remain mocked by scope, but the application should still have a production
authentication shape.

## Decision

- `AUTH_MODE=mock` maps `X-Mock-User` to local mock users. It is allowed only
  when `ENVIRONMENT` is `local` or `test`.
- `AUTH_MODE=jwt` verifies HS256 tokens with a configured secret, issuer and
  audience.
- `AUTH_MODE=oidc` verifies RS256/ES256 tokens through a cached JWKS client.
- A middleware authenticates every non-public route, attaches a
  `RequestContext` to `request.state`, and returns a request ID.
- Production configuration fails at startup if mock auth is selected, a JWT
  secret is missing, or OIDC issuer/JWKS settings are incomplete.
- A local mock IdP (`itinerary_agent.mock_services.identity`) issues
  verifiable HS256 tokens for development.

## Consequences

- The Vue console still uses mock headers by default; P1 adds login and token
  handling.
- Roles continue to drive admin checks. `scopes` are present in the context
  and JWT claims for later route-level enforcement.
- A production identity provider replaces the mock IdP without changing
  application services.
