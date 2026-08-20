# ADR 0489: Harden inventory-reversal trigger execution for least-privilege roles

- **Date:** 2026-08-10
- **Status:** Accepted
- **Decision:** Run the three PostgreSQL inventory-reversal trigger functions as
  `SECURITY DEFINER` functions owned by the schema migration role, with the
  fixed `search_path = pg_catalog, reconforge`. Additive Alembic revision
  `0085_pg_reversal_definer` reapplies the idempotent schema definition so
  existing installations receive the hardening; its downgrade restores
  `SECURITY INVOKER` and resets the function search path without deleting
  evidence tables.
- **Rationale:** A non-superuser application role inserting an ordinary
  Finance Core entry can still fire an immutable-evidence trigger. The trigger
  must inspect protected reversal rows without granting the application role
  broad read access to the reversal evidence tables. A fixed search path keeps
  the definer boundary from resolving attacker-controlled objects.
- **Verification:** The live Finance Core HTTP test passes with a
  non-superuser/non-BYPASSRLS role after upgrading to Alembic 0085. The
  expanded disposable PostgreSQL boundary suite passes 330 tests; full local
  regression, Ruff, Mypy, Bandit, pip-audit, package build, and web gates also
  pass. Native `pg_dump`/`pg_restore` smoke and the Redis live report pass in
  disposable containers.
- **Boundary:** This proves a single-node synthetic PostgreSQL privilege and
  trigger boundary only. It does not prove HA/DR, RPO/RTO, hosted CI, live
  bank/ERP providers, write-back, statutory posting, or production readiness.
- **Rollback:** Run `alembic downgrade 0084_pg_bank_statement` to remove the
  definer attributes only, then restore the previous migration head if the
  operator has verified the guarded evidence state. No evidence rows are
  deleted by this revision.
