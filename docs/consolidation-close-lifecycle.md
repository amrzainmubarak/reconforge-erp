# Consolidation Close Lifecycle

This experimental Finance Core slice persists one replay-valid worksheet v1
artifact into a local SQLite consolidation control journal. It is a library and
database boundary only. There is no CLI, API, UI, live connector, source-system
write-back, statutory statement, or legal-book posting.

## Scope

The lifecycle uses migration 25 and the
`SQLiteConsolidationCloseRepository` adapter behind the backend-neutral
`ConsolidationCloseApplicationService`.

Supported local states:

- `Prepared`
- `Approved`
- `Posted`
- `ReversalPrepared`
- `Reversed`

Period states are `Open`, `Locked`, and `Reopened`. Every lock/reopen writes an
immutable event so a period that is locked, reopened, and locked again can be
replayed without losing the earlier transition.

## Financial Controls

- Only a verified worksheet with `posting_effect=none` can be prepared.
- The authenticated preparer must match the worksheet preparer.
- Journal lines are derived from worksheet eliminations, sorted canonically, and
  must balance exactly in integer minor units.
- Approval, posting, reversal request, reversal approval, lock, and reopen are
  optimistic row-version transitions with explicit actor, reason, and UTC time.
- Posting creates a committed `Posting` effect that exactly reproduces the
  governed run lines.
- Reversal creates a committed `Reversal` effect that exactly negates the
  posting effect. Neither effect can be edited or deleted.
- Locks require final runs prepared before the lock time and no unfinished run
  at that time. A locked period blocks new runs and lifecycle changes until an
  independent reopen.

## Backup And Restore

`reconforge db backup` includes:

- `consolidation_close_periods`
- `consolidation_period_events`
- `consolidation_runs`
- `consolidation_run_lines`
- `consolidation_effects`
- `consolidation_effect_lines`

Restore loads base period/run rows, restores immutable line details, replays
approvals, posting effects, reversal effects, and period events through the
SQLite triggers, then calls the consolidation integrity verifier. If a backup
omits required lifecycle tables, contains orphan effects/events, or tampers with
a stored worksheet payload, restore fails before replacing the selected target
database.

## Current Limits

- PostgreSQL control-journal/run-line replay and certification parity exists for
  the bounded server contract; complete close mutation and statutory lifecycle
  parity remain out of scope.
- Read-only hosted API and local CLI drill-downs exist; no Studio workflow for
  this lifecycle is claimed.
- Non-posting acquisition fair-value/goodwill and item-level PPA artifacts plus
  effective-dated ownership evidence exist. Statutory acquisition accounting,
  equity-method/joint-arrangement accounting, remeasurement, statement
  presentation, tax, impairment, payment execution, or ERP/bank write-back do
  not.
- `Posted` is local control-journal evidence only. It is not a statutory posting
  and does not validate or mutate Finance Core entries.
- Local actor labels are not SSO/MFA assurance.

## Verification

```bash
python -m pytest tests/test_sqlite_consolidation_close.py -q
python -m pytest tests/test_consolidation_translation.py tests/test_consolidation_lifecycle.py tests/test_sqlite_consolidation_close.py -q
python -m pytest tests/test_db_backup_restore.py tests/test_backup_restore_matrix.py tests/test_db_backup_structured_ingress.py tests/test_encrypted_backup.py tests/test_durable_job_backup_export.py tests/test_enterprise_db.py -q
python -m ruff check reconforge tests/test_sqlite_consolidation_close.py
python -m mypy reconforge
```

See ADR 0212 for the decision and rollback boundary.
