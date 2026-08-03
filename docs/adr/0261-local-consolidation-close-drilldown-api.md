# ADR 0261: Local consolidation-close drill-down API

- Status: accepted
- Date: 2026-08-03

## Context

The local SQLite consolidation-close lifecycle already persists immutable
periods, replayable worksheets, journal lines, and effects, but its evidence
was primarily available through repository and CLI surfaces. A read surface is
needed for a team workflow without creating an ungoverned posting endpoint.

## Decision

Add a separate `/api/v1/consolidation-close` router with permissioned, read-only
period, run, detail, and summary endpoints. The authenticated local user is
passed as the repository actor. Workspace list operations are explicit, and
run details use the repository's replay, balance, attribution, and digest
verification before serialization.

## Consequences

Team clients can drill down from a close run to its worksheet, journal lines,
and effects with fail-closed integrity checks. The route adds no migration and
cannot post, reverse, reopen, or contact a source system. PostgreSQL
consolidation parity, statutory reporting, UI mutation, and production close
evidence remain separate gates.
