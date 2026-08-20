# PostgreSQL outbox consumer crash-recovery profile v1

## Profile

- Database: PostgreSQL 16 Alpine, non-superuser application role with
  `NOBYPASSRLS`.
- Workload: one tenant, one event, one consumer, one synthetic database-local
  effect.
- Failure point: consumer transaction commits, then the publisher does not
  acknowledge the outbox row; the lease is expired and reclaimed.
- Acceptance: exactly one effect row, exactly one immutable receipt, replay
  status `duplicate`, published outbox status, and changed-digest rejection.

## Reproduction

```powershell
$env:RECONFORGE_TEST_POSTGRES_DSN='postgresql://reconforge_app:***@localhost:55433/reconforge'
$env:RECONFORGE_TEST_POSTGRES_ADMIN_DSN='postgresql://postgres:***@localhost:55433/reconforge'
$env:RECONFORGE_TEST_POSTGRES_APP_USER='reconforge_app'
python -m pytest -q tests/test_postgres_outbox_consumer.py::test_live_postgres_consumer_receipt_prevents_duplicate_effect_after_ack_crash
```

## Result

Local live PostgreSQL 16 profile passed on 2026-08-03. The test is synthetic
and single-node; its runtime is not a throughput or availability claim.
