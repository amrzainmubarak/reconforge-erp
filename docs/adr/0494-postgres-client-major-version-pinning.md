# ADR 0494: Match PostgreSQL native client major version to the CI service

- **Status**: Accepted
- **Date**: 2026-08-10
- **Context**: The server-boundaries job runs a pinned PostgreSQL 16 service and
  exercises encrypted native backup and isolated restore. A PostgreSQL 17
  `pg_restore` against that service emits `SET transaction_timeout = 0`, which
  PostgreSQL 16 rejects. The dump is produced, but restore fails before the
  release gate can verify the artifact.
- **Decision**: Install `postgresql-client-16` alongside `libpq-dev` in the
  server-boundaries job and fail closed unless both `pg_config` and `pg_dump`
  report major version 16. Resolve all five binaries from the `pg_config`
  bindir as before; do not rely on ambient command wrappers or a newer client.
- **Verification**: The phase-4 workflow contract asserts the matched package
  and major-version checks. The pinned PostgreSQL 16 image accepts the same
  custom-format dump/restore command shape; a mismatched 17-to-16 probe is
  retained as a compatibility finding rather than being allowlisted.
- **Boundary**: This closes client/service version selection for the CI
  PostgreSQL 16 backup gate. It does not establish hosted backup/restore,
  cross-major restore support, PITR, HA/DR, or production RPO/RTO.
- **Rollback**: Revert the workflow/test/ADR change and restore the generic
  client package only if the service major version and a fresh restore proof
  are changed together.
