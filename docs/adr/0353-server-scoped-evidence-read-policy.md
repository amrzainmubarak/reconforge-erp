# ADR 0353: Server evidence reads re-evaluate central policy

- Status: accepted for the Phase 4 IAM adoption slice
- Date: 2026-08-05

## Decision

PostgreSQL evidence list, coverage, record, and non-sensitive drill-down reads
must re-evaluate the central `evidence.read` OR `evidence.manage` policy against
the authenticated tenant/workspace immediately before repository access. A
sensitive drill-down continues to require `evidence.manage` through the
existing dedicated path; it does not weaken to a read grant.

## Rationale

The regular FastAPI permission dependency proves only that a principal has a
named capability. Server-mode evidence reads also need the selected tenant and
workspace bound at the repository boundary. Applying the same central gate to
read projections closes a route-family gap without changing local SQLite
compatibility or sensitive-field authorization.

## Evidence and boundary

- `tests/test_api_server_evidence.py` passes the tenant-scoped repository path
  and captures all read/manage/verify policy calls.
- Ruff, Mypy, and `git diff --check` pass for the changed route/test.
- This is route IAM evidence only; it does not prove worker/export/UI-wide
  adoption, federation, distributed invalidation, live providers, HA/DR,
  compliance, or production IAM assurance.

## Rollback

Remove the read helper calls, focused assertions, ADR, manifest and execution
records. No schema or data rollback is required.
