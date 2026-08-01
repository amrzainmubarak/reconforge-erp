# ADR 0140: Account-reconciliation application boundary

- Status: Accepted
- Date: 2026-07-28

## Decision

Move all account import, template, creation, preparation, submission, review,
completion, roll-forward, list, and read behavior behind one typed application
port. Keep SQLite, WorkflowService participation, exact Decimal persistence,
audit, outbox, and transaction ownership in the infrastructure adapter. Preserve
the connection constructor through a SQL-free Platform facade.

## Consequences

Business and workflow state cannot be separated accidentally by application
orchestration. Existing callers, schemas, statuses, IDs, CLI, and backup format
remain compatible. PostgreSQL parity remains a later gate.
