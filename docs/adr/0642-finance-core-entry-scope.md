# ADR 0642: Refuse incomplete Finance Core entry scope before legacy fallback

- Status: Accepted
- Date: 2026-08-26
- Scope: PostgreSQL Server Profile Finance Core entry creation

## Context

The Finance Core entry route historically selected its PostgreSQL Finance Core
adapter only when `entity_code`, `period_id`, and `journal_code` were all
present. In Server Profile, the same application state also exposed the older
tenant-scoped ledger adapter. An incomplete Finance Core request could
therefore fall through to a different persistence contract with different
scope and lifecycle semantics.

## Decision

When the Finance Core server backend is enabled, entry creation always enters
the Finance Core route boundary. The route requires non-empty `entity_code`,
`period_id`, and `journal_code`; otherwise it returns
`finance_core_entry_scope_required` before calculating policy amount or calling
either adapter. Valid requests retain the existing scoped Finance Core path.
Local Profile continues to use the existing SQLite service.

## Consequences

- Server Profile cannot silently reinterpret an incomplete Finance Core request
  as a legacy ledger write.
- Clients receive a stable validation error and must provide the full Finance
  Core scope.
- This is a compatibility-tightening change for ambiguous requests, with no
  migration or data rewrite. Explicit legacy ledger calls remain separate.
- The decision does not claim legacy ledger removal, hosted parity, external
  IAM, HA/DR, provider integration, capacity, production readiness,
  compliance, or certification.

## Verification and rollback

- A route regression asserts that incomplete scope invokes neither adapter.
- Focused Finance Core tests, Ruff, Mypy, and diff-check pass; live PostgreSQL
  verification remains opt-in and capability-gated.
- Roll back by reverting the route guard, regression, execution records, claims
  row, and this ADR together. No persisted state rollback is required.
