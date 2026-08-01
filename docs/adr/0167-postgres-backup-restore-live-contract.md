# ADR 0167: PostgreSQL backup and isolated restore live contract

## Status

Accepted — 2026-07-28

## Context

The authorized PostgreSQL native adapter already encrypted custom dumps,
authenticated before restore, created a new database, verified the restored
schema, and removed tested partial targets. Its tests used a closed fake command
runner, while an older manual native-tool drill did not execute the adapter
end-to-end. The parity inventory therefore correctly retained the boundary as
contract-only. Restore outcomes also hashed the input in a separate pass before
decryption, so the reported artifact identity was not derived from the exact
ciphertext stream consumed by the authenticated restore.

## Decision

Compute the restore artifact SHA-256 while reading the authenticated envelope:
magic/header, ciphertext, then GCM tag in their stored order. Return that digest
only after GCM authentication and plaintext digest/size verification succeed.

Add an opt-in live contract requiring explicit disposable libpq source and
maintenance service names and absolute native tools resolved from `PATH`. Each
run chooses a random conservative database name, exercises the authorized
Application service through encrypted backup and isolated restore, compares the
create/restore artifact identities, and drops that exact target in `finally`.
If cleanup fails, the test fails with the exact non-secret database name. The
test remains skipped unless both service variables are configured.

## Consequences

All 26 Application boundaries now have either a pure-strategy classification or
a PostgreSQL live test path; none remain contract-only or absent. This is test
availability, not current live proof. Operators must never provide a production
maintenance role to the rehearsal. Managed key lifecycle, scheduled/immutable
storage, host-loss and HA recovery, cross-version support, and measured RPO/RTO
remain separate deployment evidence.
