# ADR 0641: Bind Finance Core hierarchy selectors to authenticated scope

- Status: Accepted
- Date: 2026-08-26
- Scope: PostgreSQL Server Profile Finance Core API

## Context

Finance Core routes accept organization and legal-entity codes because the
domain repository uses stable business selectors. In Server Profile, the
authenticated request already carries tenant, workspace, organization, and
legal-entity IDs. Trusting a different payload code could therefore create a
confusing authorization boundary: the central policy would authorize one
hierarchy while the repository receives another selector.

## Decision

Add a request-scoped Finance Core executor that, inside the same
`PostgresTenantBoundary` transaction:

1. Resolves organization and legal-entity codes from the authenticated IDs.
2. Verifies that the authorized organization is linked to the workspace.
3. Rejects a non-empty payload selector that differs from the canonical code.
4. Injects the canonical code into repository writes and filtered reads.

The boundary is used by chart, account, dimension, journal, trial-balance,
entry-list, and entry-creation paths. Existing unscoped Finance Core adapter
callers remain available for compatibility, and Local Profile continues to use
the existing SQLite service.

## Consequences

- A payload cannot redirect a scoped request to a sibling organization or legal
  entity through a business-code field.
- Omitting a selector in a scoped request is safe: the authenticated canonical
  value is used for persistence or filtering.
- Scope lookup adds bounded reads to the same transaction; no network call or
  new persisted schema is required.
- Live PostgreSQL verification remains capability-gated when the declared test
  DSN is unavailable. This ADR does not claim hosted parity, external IAM,
  HA/DR, provider integration, capacity, production readiness, compliance, or
  certification.

## Verification

- Direct unit coverage proves canonicalization and organization/entity spoof
  rejection.
- Focused Finance Core route, application, domain, PostgreSQL adapter, Ruff,
  Mypy, and diff-check gates pass.
- `tests/test_api_server_finance_core_live.py` remains an explicit opt-in live
  PostgreSQL/RLS contract and is skipped without
  `RECONFORGE_TEST_POSTGRES_DSN`.

## Rollback

Revert the Finance Core scoped executor, route dispatch changes, focused tests,
execution records, claims row, and this ADR together. No migration or external
state rollback is required.
