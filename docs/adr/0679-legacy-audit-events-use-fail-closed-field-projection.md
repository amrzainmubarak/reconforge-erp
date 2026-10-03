# ADR 0679: Legacy audit event responses use fail-closed field projection

## Status

Accepted for the E-1019 slice on 2026-08-26.

## Context

The consolidated PostgreSQL administration audit route already returned a
redacted, chain-specific contract. The compatibility route at
`/api/v1/audit/events`, however, serialized the local SQLite audit model and
the PostgreSQL ledger adapter response directly. Depending on the backend,
that exposed actor identifiers, object/resource identifiers, request IDs,
reasons, and decoded metadata to any principal with `audit.read`. It also
allowed a future adapter field to escape simply by being added to a returned
mapping.

## Decision

1. Add one central `project_audit_event` policy for the two physical legacy
   shapes. It accepts only reviewed response fields and masks sensitive aliases
   (`actor_*`, object/resource IDs, tenant, request ID, reason, and metadata)
   with the existing `[REDACTED]` token.
2. Apply the projection after both the local SQLite model dump and the
   PostgreSQL ledger adapter, before the response leaves the route.
3. Preserve field names and non-sensitive values for compatibility, but never
   return sensitive values or unknown future fields from this route.
4. Keep audit verification unchanged: verification hashes and chain results
   are not disclosure of the underlying audit payload.

This is a response-disclosure control, not an authorization replacement. The
route still requires `audit.read` and Server Profile still re-evaluates the
tenant policy. The consolidated `/api/v1/admin/audit/*` contract remains the
preferred human-governed browsing surface.

## Evidence and limits

- `tests/test_field_access.py` covers sensitive aliases, unknown-field denial,
  and digest stability when masked source values change.
- `tests/test_api_audit_workflow.py` covers the local HTTP boundary.
- `tests/test_api_server_audit_policy.py` covers the PostgreSQL compatibility
  boundary and policy re-check.
- This does not prove external IAM, distributed revocation, disclosure
  approval workflows, source authenticity, or production effectiveness.

## Rollback

Revert this ADR, the central audit projection, route calls, tests, and
execution records together. Do not restore direct serialization without either
an approved versioned disclosure contract or an equivalent fail-closed policy.
