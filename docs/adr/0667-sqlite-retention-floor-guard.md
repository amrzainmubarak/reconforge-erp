# ADR 0667: SQLite evidence-retention floor and version guard

- Status: Accepted
- Date: 2026-08-26
- Owners: Evidence / Platform / Security

## Context

The SQLite evidence registry stored `retention_until`, but its conflict upsert
replaced that value during re-registration. A later request could therefore
shorten an existing evidence floor. The object-store provider contract and the
PostgreSQL governance path already treated retention as a floor; the local
database needed the same invariant and an independent database backstop.

## Decision

Add SQLite migration 46 with `evidence_registry.retention_version`, defaulting
existing rows to version 1, and a `BEFORE UPDATE` trigger. The trigger rejects a
shorter or cleared floor, malformed new timestamps, and version changes that
do not correspond to a strict retention extension. The repository validates the
transition before uploading bytes, preserves the current floor for an equal or
omitted request, and increments the version only for an extension. Backup and
restore explicitly carry the version field.

Keep the pre-46 compatibility path for databases opened before the migration
command. Once migration 46 is applied, both the service boundary and SQLite
trigger enforce the invariant.

## Verification and boundaries

E-973 tests prove service-level pre-upload rejection, extension versioning,
direct-SQL trigger refusal, backup preservation, and additive migration from an
older SQLite version. This is a local synthetic integrity control. It does not
establish legal hold, authorized deletion, WORM/object-lock behavior, provider
durability, privacy erasure, or production governance.

## Rollback

Before accepting a database that depends on migration 46, revert the repository
handling, backup field, tests, documentation, and migration entry together.
SQLite does not support a safe in-place downgrade of this additive column and
trigger; a downgrade must use the existing versioned backup/restore procedure
and must be validated against a copy before any operator action.
