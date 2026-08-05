# ADR 0354: Legacy PostgreSQL audit views re-evaluate tenant policy

- Status: accepted for the Phase 4 IAM adoption slice
- Date: 2026-08-05

## Decision

The legacy PostgreSQL ledger audit endpoints `/audit/events` and
`/audit/verify` re-evaluate `audit.read` and `audit.verify` respectively with
the validated request tenant before opening the tenant-scoped ledger adapter.
These views have no workspace key, so the central tenant-wide helper is used
without inventing a workspace.

## Rationale

The regular permission dependency proves capability but does not bind it to a
selected server tenant. The newer audit-administration views already had this
boundary; bringing the legacy ledger views onto the same gate prevents a
route-family authorization gap while preserving local SQLite compatibility.

## Evidence and boundary

- `tests/test_api_server_audit_policy.py` captures both policy calls and the
  tenant-bound fake adapter; server identity and audit administration tests also
  pass.
- This is tenant-wide route IAM evidence only. It does not prove complete
  worker/export/UI adoption, federation, distributed invalidation, live
  providers, independent HA/DR, compliance, or production IAM assurance.

## Rollback

Remove the two helper calls, focused test, ADR, manifest and execution records;
no schema or data rollback is required.
