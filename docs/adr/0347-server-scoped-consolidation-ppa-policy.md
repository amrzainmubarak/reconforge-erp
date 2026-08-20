# ADR 0347: Bind server-profile consolidation PPA routes to tenant policy

- **Date**: 2026-08-05
- **Status**: Accepted

## Context

The PostgreSQL consolidation PPA API persists tenant-scoped, non-posting
acquisition evidence. Its FastAPI dependencies prove the caller has the
appropriate local permission, but the route boundary must also re-evaluate
that permission against the authenticated request tenant immediately before
the persistence/read adapter.

## Decision

Use the central server policy evaluator for both PPA routes. Preparation
requires `finance_core.manage`; reads retain the existing
`finance_core.read` OR `finance_core.manage` contract. The evaluator receives
the validated request tenant and an explicit `None` workspace because the
persisted PPA schema is tenant-scoped and has no workspace key.

## Consequences

- A sibling tenant supplied in `X-ReconForge-Tenant` fails closed before PPA
  repository access.
- Local SQLite compatibility and the non-posting PPA contract are unchanged.
- This does not establish statutory acquisition accounting, tax/impairment
  treatment, provider interoperability, write-back, HA/DR, or production
  readiness; complete worker/export/UI policy adoption remains open.

## Verification and rollback

`tests/test_api_consolidation_ppa.py` verifies the tenant-policy call shape;
`tests/test_api_server_identity.py` retains the authenticated PostgreSQL PPA
route lifecycle. Rollback removes the helper calls, focused test, ADR, and
manifest entry; no migration or data rewrite is required.
