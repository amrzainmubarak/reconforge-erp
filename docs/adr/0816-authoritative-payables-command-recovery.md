# 0816: Authoritative PostgreSQL payables command recovery

Status: accepted for PO, goods-receipt and supplier-invoice recovery, 2026-10-03.

## Observed failure

Actual nonowner PostgreSQL keyed creation retries failed for all three AP
commands. JSONB arrived as a mapping and str(mapping) was invalid JSON for the
existing bounded persisted decoder. A subsequent independent review found that
an identical PO/invoice retry also failed after a parent became inactive.
Initial branch creation exposed a preexisting untyped nullable SQL parameter.

## Decision

Read cached JSONB as explicit SQL text and keep the bounded shared decoder.
Retain a closed version1 payables.command.request-response envelope with a
canonical digest of every normalized creation input. Independently derive the
requested source ID; re-read the authoritative aggregate under current RLS,
workspace and hierarchy; verify original creation fields, line identities,
initial response version and closed shape; return the current aggregate.
Retries serialize on the existing transaction-scoped advisory lock and create
no new financial audit/outbox effect. Changed requests and borrowed/invalid
evidence fail closed.

For recovery, resolve the current authorized parent identity even when inactive.
For a cache miss, repeat the existing active supplier/organization/entity/branch
and currency prerequisites before insertion. Type the optional branch SQL text
parameter explicitly. Recovery does not reactivate a parent or authorize a new
purchase. Public response shapes and SQLite AP semantics remain unchanged.

Legacy raw creation responses remain verifiable only where their full original
content and current authoritative source are retained. Raw goods-receipt caches
do not contain original parent hierarchy; current GET/replay use the current
authorized PO, without inventing historical scope. New envelope request digests
bind the parent hierarchy and reject reattribution. Synthetic administrative
reattribution demonstrated this limitation but no current-scope leakage or
repeat business effect. Database owners remain a trusted boundary.

## Evidence and limits

PAYABLES_COMMAND_RECOVERY_2026-10-03.json binds the final145pass/0skip gate,
unchanged11 dependency hashes, actual limited-role PostgreSQL, concurrency lock
waits, password/step-up HTTP, inactive-parent recovery/fresh-write denial,
owned database removal and Ruff/Mypy/Bandit. The original138-pass source and
three JSONB failures remain separate. Failed concurrency/HTTP audit-count and
branch fixtures are classified and retained; they are not relabeled as passes.

This slice supplies no AP payment aggregate, bank execution, new stable AP
maker/checker identity, Inventory or operational GL composition. Rollback can
restore previous code without schema migration, but newer envelopes must remain
readable for recovery; reverting their verification would restore weaker checks.
