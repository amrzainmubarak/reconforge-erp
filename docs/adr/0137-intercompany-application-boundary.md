# ADR 0137: Intercompany application boundary

- Status: Accepted
- Date: 2026-07-28

## Context

The intercompany Platform service combined exact financial input, persistence,
matching policy, exception creation, settlement, and evidence commits. It could
also commit settlement audit/outbox evidence for an ID that did not identify a
case, because row existence was checked only after commit.

## Decision

Define one backend-neutral port covering import, match, settle, list, and get.
Move SQLite behavior into an infrastructure adapter and preserve the historical
Platform constructor as a compatibility facade. Use Decimal and canonical text
for amounts, include stable transaction IDs in matching order, keep case,
exception, outbox, and audit effects in one transaction, and require one case
row to be updated before settlement evidence is emitted.

## Consequences

Application orchestration is database-independent and the local adapter has
explicit rollback behavior. Missing-case settlement fails without producing
orphan evidence. Existing callers and persisted schemas remain compatible.

PostgreSQL parity, concurrent settlement fencing, entity-level authorization,
and supported-scale claims remain separate gates. Reverting the module split is
possible, but restoring the orphan-evidence behavior is not acceptable.
