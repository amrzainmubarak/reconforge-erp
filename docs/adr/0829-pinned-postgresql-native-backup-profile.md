# ADR 0829: Bind PostgreSQL Native Backups To Named Recovery Profiles

- Status: Accepted
- Date: 2026-10-04
- Scope: `PostgresNativeBackupAdapter` encrypted native backup and isolated restore

## Context

The native PostgreSQL adapter already creates an encrypted custom-format dump
and restores only into a newly created target database. Its post-restore check
previously established only that `reconforge.tenants` and
`public.alembic_version` existed. A dump at an unintended revision could
therefore pass the adapter's structural check, even though the deployment's
recovery procedure expected another schema revision.

The adapter also had no authenticated association between a new artifact and
the operator's declared recovery profile. The encryption header is associated
data for AES-GCM, so it can carry a bounded profile/revision identity without
adding a second format or a separate sidecar file.

## Decision

1. `PostgresBackupSettings` accepts an optional atomic pair:
   `recovery_profile` and `expected_alembic_revision`. Both must be supplied
   together. A profile is a bounded deployment label; a revision uses the
   repository's four-digit Alembic revision syntax.
2. A named profile verifies the source service with a closed `psql` query
   before `pg_dump`. The query requires one `public.alembic_version` row equal
   to the configured revision and the required `reconforge.tenants` relation.
   The revision crosses the process boundary through quoted `psql` variable
   substitution, never SQL string construction.
3. New profile-bound artifacts add `recovery_profile` and `alembic_revision`
   to the existing encrypted header. These fields remain readable metadata but
   are authenticated as AES-GCM associated data. A configured mismatch stops
   before `pg_restore --list`, isolated-target creation, or any target
   database mutation.
4. Target creation is non-connectable. A maintenance-database transaction
   removes `PUBLIC CONNECT` while enabling the restore owner's connection path
   before `pg_restore`; after restore, the adapter re-revokes `PUBLIC EXECUTE`
   on restored user-schema `SECURITY DEFINER` routines before the same
   exact-revision query runs. Failure invokes the existing exact-target
   `dropdb` rollback.
5. Existing unbound v1 artifacts and settings remain readable. They retain the
   historical relation-existence gate. A named profile may restore an unbound
   artifact only if the exact target-side revision verification passes; an
   unbound configuration refuses a profile-bound artifact rather than silently
   discarding its binding.
6. The existing application service remains the authorization boundary:
   `operations.backup.create` is required before backup and
   `operations.restore.execute` before restore. This adapter has no HTTP route
   or new database schema of its own.

## Consequences

- Profile-bound recovery has a source preflight, authenticated artifact
  identity, pre-target mismatch rejection, and exact target verification.
- The recovery profile is deployment configuration, not a general claim that
  all PostgreSQL backup callers use the stronger path. Existing callers keep
  their compatibility behavior until configured with the pair.
- The focused fake-native-tool contract covers non-connectable target creation,
  atomic `PUBLIC CONNECT` removal, security-definer hardening, failure
  ordering, and rollback behavior. It does not establish a live native-client
  service rehearsal, backup duration, throughput, RPO/RTO, key custody,
  maintenance-role custody, HA/DR, or production recovery readiness.

## Rollback

Revert the adapter and configuration changes. Older unbound v1 artifacts
remain readable by the preserved header reader; no database migration or
persisted data rewrite is involved.
