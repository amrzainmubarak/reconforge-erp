# ADR 0484: Local bank-statement evidence persistence boundary

## Context

The deterministic CAMT.053-to-ledger control already produced a self-digesting,
non-posting report and a read-only Studio projection, but it had no authenticated
local evidence-store projection. That made replay, workspace retention, and local
backup/restore less complete than the retail, professional, and manufacturing
control slices.

## Decision

Additive SQLite migration 39 introduces `bank_statement_control_runs` with an
immutable trigger, workspace-scoped uniqueness, bounded JSON persistence, and
outer artifact/decision/status-digest checks. The local API exposes authenticated
create/list/read routes under `/api/v1/bank/statement-controls`; it explicitly
returns `network_dispatch: disabled` and refuses the PostgreSQL server profile
until a separate PostgreSQL parity slice exists.

The repository accepts only replay-verified reports using exact serialized
financial values. Identical decision digests are idempotent within a workspace;
conflicting artifacts fail closed. Backup/restore includes the table and the
existing audit boundary.

## Evidence boundary

Focused SQLite, API, authorization-inventory, migration, and backup/restore tests
pass locally. This is synthetic local evidence only. It does not prove a live
bank provider, source authenticity, payment initiation, ledger posting, ERP
write-back, PostgreSQL parity, HA/DR, or production operations.

## Rollback

The migration is additive and has no destructive downgrade path in the local
runner. To roll back application code, stop using the routes and restore a
pre-migration backup; do not delete the table in place because evidence rows are
immutable by policy.
