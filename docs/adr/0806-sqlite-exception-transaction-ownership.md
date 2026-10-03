# ADR 0806: Keep exception evidence inside the owning SQLite transaction

Date: 2026-10-03

Status: Accepted

## Context

AP three-way matching uses the exception repository with `autocommit=False`.
Both branches of that repository's finalizer called `commit_audited`, which
committed the connection. A subsequent AP audit or outbox failure could leave
an Exception invoice, match row, exception and exception audit committed without
the final AP evidence. An eleven-case synthetic reproduction distinguishes this
existing partial-commit defect from the separate future posting-UoW gaps.

## Decision

Keep default standalone behavior and the shared `commit_audited` helper unchanged.
In the exception adapter only, `autocommit=False` appends existing sanitized audit
evidence into the active caller transaction and leaves commit/rollback to the
caller. Refuse evidence finalization without an active transaction. Translate
audit failures into the existing `PlatformError` contract so aggregate owners
execute their existing rollback path. INSERT/UPDATE error handling must also
preserve caller-owned pending work rather than rolling it back internally.

The caller remains responsible for rolling back a failed aggregate. This option
does not create savepoints or make a failed child safe to ignore and commit.
Do not infer ownership merely from `connection.in_transaction`: existing writers
start implicit DML transactions and rely on explicit finalization for durability.

## Verification and compatibility

Database-trigger failure injection covers final AP audit and outbox writes for
both Passed and Exception match results. Independent readers observe unchanged
pre-command state after failure, including the audit head; a deliberate retry
after removing the injected fault records one complete effect. Tests also verify
standalone durability, caller commit/rollback, uncommitted invisibility, audit
and SQL refusal preserving caller work, and empty bulk operations refusing to
start a hidden transaction. The complete focused selection passes54 tests in
17.55s. Ruff, source Mypy and diff checks pass. Source hashes and failed attempts
are retained in [verification](../execution/SQLITE_EXCEPTION_ATOMICITY_2026-10-03.json).

The after-fix eleven-case replay has zero persisted AP deltas after injected
failure. Generic Finance/AR/Inventory nesting and early commits remain open under
PROD024. The next integrated event should extract explicit transaction-bound
primitives while retaining standalone wrappers, not globally suppress commits.

No schema or API migration is required. Rollback restores the partial-commit
defect, so recovery should retain this guard or restrict affected match workflows.
This choice follows SQLite's explicit transaction/savepoint behavior; it adds no
new transaction mechanism. [Official SQLite transaction documentation](https://www.sqlite.org/lang_transaction.html)
was checked on2026-10-03.
