# ADR 0656: Add a regression gate for mutating route server boundaries

- Date: 2026-08-26
- Status: accepted
- Scope: API route source inventory and E-1005 governance regression

## Context

The route authorization inventory already rejects unclassified endpoints and
requires permission-bearing mutations. That does not by itself prove that a
new mutating route either re-evaluates tenant/workspace policy in Server
Profile or explicitly refuses a local-only surface. E-961 exposed this exact
class of drift in the individual cashflow route.

## Decision

Add a deterministic AST-backed test over `reconforge/api/routes/*.py`. Every
module containing a mutating route decorator must include a reviewed server
boundary marker (`enforce_server_scoped*`, `enforce_server_tenant*`, or
`server_identity_enabled`) unless it belongs to the explicit authentication,
SCIM, or WebAuthn protocol allowlist. The existing route authorization
inventory remains the authoritative per-route permission contract; this gate
is an additive source-level reminder that scope or fail-closed review cannot
be silently omitted by a new module.

## Consequences

- A new mutating route module without a visible server boundary fails tests
  before it can be treated as globally governed.
- Protocol handshakes remain explicit exceptions and are visible in one small
  reviewed allowlist.
- The marker gate is intentionally conservative and does not claim that a
  marker alone proves correct policy arguments, RLS, SoD, or production IAM;
  route-specific tests and runtime evidence remain required.
- No runtime API, schema, database, or compatibility behavior changes.

## Verification and boundary

E-962 runs the full authorization inventory and Python regression with the new
gate. It provides source-level omission detection only; it does not close
universal worker/export/UI adoption, distributed invalidation, external IAM,
live providers, HA/DR, or production authorization effectiveness.

## Rollback

Revert the test, ADR, and E-962 execution records. No data or migration
rollback is required.
