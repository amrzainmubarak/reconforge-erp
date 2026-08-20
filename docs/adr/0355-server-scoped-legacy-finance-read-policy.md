# ADR 0355: Legacy PostgreSQL Finance Core reads re-evaluate tenant policy

- Status: accepted for the Phase 4 IAM adoption slice
- Date: 2026-08-05

## Decision

The tenant-scoped legacy PostgreSQL ledger branches for summary, accounts,
trial balance, entry listing, and entry lookup re-evaluate
`finance_core.read` before adapter access. Existing account/entry mutations
retain `finance_core.manage` with the authenticated workspace scope. The read
gate uses tenant-wide semantics because this legacy ledger boundary explicitly
does not support workspaces.

## Rationale

The newer PostgreSQL Finance Core adapter already bound its hierarchy, but the
compatibility ledger path could reach a tenant-scoped repository after only a
dependency-level permission check. Re-evaluating the read permission closes
that boundary without inventing unsupported workspace state or changing local
SQLite behavior.

## Evidence and boundary

- `tests/test_api_server_legacy_finance_policy.py` captures five read gates
  before a fake tenant adapter; server identity and Finance Core route tests
  pass.
- This is route IAM evidence only. It does not prove statutory posting,
  complete worker/export/UI adoption, federation, distributed invalidation,
  live providers, HA/DR, compliance, or production IAM assurance.

## Rollback

Remove the helper calls, focused assertions, ADR, manifest and execution
records; no schema or data rollback is required.
