# ADR 0262: PostgreSQL consolidation-close replay and period SoD

- Status: accepted
- Date: 2026-08-03

## Context

The PostgreSQL consolidation-close gate exercised lifecycle persistence,
tenant isolation, and control-journal effects. Idempotent run identifiers could
still return conflicting evidence, period transitions did not preserve event
reasons or enforce independent lock/reopen actors, and JSONB reads trusted
stored payloads without reproducing the declared worksheet.

## Decision

Bind an existing run identifier to its worksheet digest and preparer. Reproduce
and verify every JSONB worksheet and journal digest before `get_run`,
`list_runs`, or summary exposure. Persist lock/reopen events with actor and
reason, and reject reopening by the actor who locked the period.

## Consequences

The live control-journal boundary is more tamper-evident and its period
maker-checker transition is explicit. The adapter remains a tenant-scoped
control ledger, not a statutory consolidation engine or ERP/bank write-back
path.
