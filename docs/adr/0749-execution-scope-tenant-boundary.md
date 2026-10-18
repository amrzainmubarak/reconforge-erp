# ADR 0749: Enforce tenant provenance in execution-scope resolution

- Status: Accepted
- Date: 2026-08-28
- Scope: PostgreSQL server execution-scope boundary

## Context

`request_execution_scope()` is called by the server business-route families to
resolve the tenant, workspace, organization, and legal-entity hierarchy before
repository work. It already checked the workspace and optional hierarchy grants
from `ServerPrincipal`, but it did not independently compare the validated
request tenant with the principal's bound tenant grant. Generic route
dependencies usually performed a related check, but the helper itself is a
security boundary used by many routes.

## Decision

After validating the request tenant and authenticated principal,
`request_execution_scope()` must reject a non-empty principal tenant grant that
does not contain the request tenant. It returns the stable `tenant_scope_denied`
API error before parsing or returning any narrower execution scope. Legacy
injected principals with an empty optional tenant grant retain the existing
compatibility behavior; real PostgreSQL-authenticated principals populate the
grant during authentication.

## Rationale

Every reusable scope resolver must be safe when called independently. Requiring
tenant provenance at this boundary prevents a future route from relying on
workspace authorization while silently accepting a sibling tenant selected by a
request header. The check complements, rather than replaces, PostgreSQL RLS,
central policy evaluation, and route permission dependencies.

## Verification

`tests/test_api_execution_scope.py` proves that a principal bound to `tenant-a`
cannot resolve a server execution scope for `tenant-b`. Existing workspace,
organization, entity, dependency, server-identity, full regression, static,
security, package, YAML, and diff gates remain required for the slice.

## Compatibility and rollback

Local SQLite routes are unchanged. The empty-grant compatibility path remains
explicit for legacy injected/test principals. Revert E-1089, this ADR, the
execution-scope/test changes, manifest entry, and execution records together.
