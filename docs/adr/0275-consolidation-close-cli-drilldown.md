# ADR 0275 — Read-only consolidation close CLI drill-down

- **Status:** Accepted
- **Date:** 2026-08-03
- **Scope:** Local SQLite consolidation-close inspection

## Decision

Add a `reconforge consolidation` CLI namespace with read-only `runs`, `run`,
and `summary` commands. The commands call the existing
`ConsolidationCloseApplicationService` and `SQLiteConsolidationCloseRepository`
and therefore reuse replay verification, workspace scoping, and the existing
`management_statement` and `translation_evidence` projections.

## Rationale

The consolidation lifecycle was already available through authenticated API
drill-down, but operators lacked a local CLI path for evidence review. A
read-only adapter improves local-first operations without duplicating
calculation logic or introducing an unreviewed mutation surface.

## Compatibility and limits

The namespace is additive and requires no migration. Unknown run IDs fail
through the existing CLI error boundary. The commands do not create, approve,
post, reverse, certify, or write back runs; they do not establish statutory
statement support, live rates, ERP/bank interoperability, HA/DR, or production
readiness. UI exposure remains a separate task.

