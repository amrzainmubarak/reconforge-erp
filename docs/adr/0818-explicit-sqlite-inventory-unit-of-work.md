# Explicit SQLite inventory transaction ownership

Status: accepted for the bounded SQLite library composition contract.
Date: 2026-10-03
Scope: PROD036, SQLite inventory Core and FIFO valuation.

Three actual synthetic probes showed different ownership faults: an inventory
master upsert committed an unrelated pending caller row; a nested movement
transaction failed and rolled that row back; FIFO approval committed its layer,
Finance Draft, audit and outbox before a later outer failure.

Use an explicit `SQLiteInventoryUnitOfWork(connection)` as the owner of one
`BEGIN IMMEDIATE` transaction. Participating Core and valuation adapters must
receive that exact active owner and connection. The owner alone finalizes.
Adapters mark caught operation failures rollback-only; catching the error does
not allow partial commit. Shared `commit_audited(autocommit=False)` appends
audit/outbox evidence inside an already active transaction and never finalizes
it. Its default remains `True` for existing independent callers.

Ordinary independent commands on a clean connection retain their behavior.
An unbound mutation on a connection with pending caller writes now fails before
touching those writes. This explicit compatibility change closes demonstrated
data-loss/early-commit paths. Callers needing composition must adopt the owner.
Custom valuation persistence cannot join without a reviewed ownership contract.

The owner does not replace permission checks, quantity/FIFO invariants,
maker/checker review, posted history or migrations. Its Finance result remains
a Draft. Generated operational GL posting, PostgreSQL bundle composition,
trade settlement and full sales/purchase cycles are separate gates.

Accepted evidence:120 local passes/three live-PostgreSQL prerequisite skips,
Ruff/Mypy/Bandit and unchanged owned sources. Tests cover SQL/audit/outbox faults,
caught child failures, deferred-FK commit failure, independent-reader visibility,
authenticated permissions, retry and cold imports. Original ownership probes
and the intermediate cold-import failure are retained separately. Independent
review found a caught custom-repository constructor rejection could leave prior
child writes committable. The repaired constructor joins the guarded operation;
21 independent tests pass without skips and the actual counterexample now rolls
back the prior unit, audit and outbox. Both final runs retained identical hashes
for all six owned files. Overlapping counts are not added.

Rollback: finish or roll back the active owner, preserve the database and
redeploy a compatible reader. No schema downgrade is needed. Reverting restores
the earlier demonstrated faults; restrict reverted calls to independent clean
connections.
