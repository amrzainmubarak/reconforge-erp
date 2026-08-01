# ADR 0151: PostgreSQL Finance Core uses exact currency minor units

- Status: Accepted
- Date: 2026-07-28

## Context

The backend-neutral Finance Core port has eighteen coupled use cases spanning
master governance, balanced draft entries, dimensions, maker-checker lifecycle,
trial balance, and bounded snapshots. Older PostgreSQL ledger and master-data
adapters implement narrower contracts and use different amount representations.

## Decision

Implement the complete port in one tenant-bound PostgreSQL adapter. Store entry
and line debit/credit values as constrained `BIGINT` currency minor units. Parse
inputs through canonical exact `Money` rules, reject binary floats and excess
currency precision, require balanced non-zero entries, and recheck all active
scope, account, period, currency, and required-dimension invariants before
validation. Draft replacement is allowed; validated lines are immutable and
correction uses explicit void lifecycle metadata. Domain audit and outbox effects
share the mutation transaction under forced tenant RLS.

## Consequences

The adapter has one representation for exact arithmetic and can reproduce the
SQLite contract without assuming two decimal places. Amounts above the signed
64-bit safety ceiling are refused. The optional live test must run under a
non-superuser, non-BYPASSRLS role before current runtime parity can be claimed.
Until then, the inventory status is `live_test_available` only.

## Rollback

Alembic downgrade 0019 drops the eight new tables in dependency order. The
existing SQLite implementation and older bounded PostgreSQL APIs are unchanged.
Downgrade destroys data in the new tables and therefore requires an export or
database backup before use outside disposable environments.
