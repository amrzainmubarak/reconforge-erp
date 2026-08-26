# ADR 0677: Evidence drill-down uses fail-closed field projection

- **Status**: Accepted
- **Date**: 2026-08-26
- **Related execution slice**: E-1017
- **Scope**: Local and Server Profile evidence drill-down responses

## Context

The evidence drill-down endpoint already required `evidence.manage` for a
sensitive request and redacted selected fields for ordinary reads.  The
repository adapters nevertheless built response records from their physical
schemas, so an added column or nested link field could escape the reviewed
response contract.  The reusable field-policy primitive existed but had no
consumer on a high-risk evidence surface.

## Decision

Use one versioned allowlist in `reconforge.auth.field_access` for every
evidence node returned by drill-down in both SQLite and PostgreSQL modes.
Ordinary reads allow only the non-sensitive response fields and mask the
existing `***redacted***` values for backward compatibility.  Sensitive reads
remain gated by `evidence.manage`, request the complete reviewed evidence
field set through the central server policy boundary, and still drop unknown
future fields.  Nested link records receive their own allowlist projection.

Each evidence node carries the projection version, mode, masked/denied field
names, and deterministic projection digest.  The graph carries the reviewed
allowlist metadata.  A malformed adapter response fails closed with a safe API
error rather than being serialized to the client.

## Consequences and boundaries

This closes one sensitive response surface and does not imply that every API,
export, worker, or UI surface has field-level enforcement.  The projection is
an output control; it does not grant `evidence.manage`, replace tenant/RLS
authorization, or expose artifact bytes.  Full hosted PostgreSQL runtime
effectiveness, external IAM, distributed revocation, and production readiness
remain unproven.

## Verification

- `python -m pytest -q tests/test_field_access.py tests/test_api_platform_routes.py tests/test_api_server_evidence.py`
- `python -m ruff check reconforge/auth/field_access.py reconforge/api/dependencies.py reconforge/api/routes/evidence.py tests/test_field_access.py tests/test_api_server_evidence.py`
- `python -m mypy reconforge/auth/field_access.py reconforge/api/dependencies.py reconforge/api/routes/evidence.py`
- Full Python regression, package build, and `git diff --check` are required
  before closing the slice.

## Rollback

Revert E-1017 route, field-policy, test, ADR, manifest, and execution-document
changes.  The rollback restores the adapter redaction behavior but does not
alter persisted evidence records.
