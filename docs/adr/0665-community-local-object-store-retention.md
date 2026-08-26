# ADR 0665: Expose offline local object retention without changing the local default

- Status: Accepted
- Date: 2026-08-26
- Owners: Platform / Security / Community Operations

## Context

ReconForge already contains `LocalObjectStore`, an offline immutable object
store with tenant/workspace/entity-separated keys, checksum manifests, bounded
object sizes, and retention-delete guards. The evidence CLI exposed only the
historical direct local-filesystem path and S3-compatible object storage. The
tested local retention primitive was therefore unavailable to Community
operators without selecting a provider-backed path.

## Decision

Add an explicit `local-object-store` value to `reconforge evidence register
--storage-backend` and `reconforge evidence verify --storage-backend`, with an
explicit bounded `--storage-root`. Keep `local` unchanged: it remains the
direct local-file registry path and rejects retention options when no object
store is configured. The offline backend makes no network calls and uses the
existing provider-neutral evidence service and local manifest integrity rules.

The database continues to use its established generic object-backed storage
label for compatibility. The selected backend is an operator configuration and
is not represented as a claim that the local manifest is WORM, legal hold, or
provider durability.

## Verification and boundaries

E-971 verifies registration and verification through the CLI, tenant/workspace
scope, checksum/retention manifest persistence, source-removal verification,
expired-retention refusal before registry persistence, and preservation of the
historical default. Focused evidence/object-storage tests, Ruff, Mypy, and the
full Python regression pass.

This is a bounded Community retention primitive. It does not close complete
retention/privacy administration, legal hold, authorized deletion/erasure,
backup/restore coupling, external object-lock propagation, WORM, independent
failure domains, or production readiness.

## Rollback

Revert the CLI options, focused tests, and documentation/evidence references.
No schema or migration rollback is required, and existing local-filesystem
evidence remains readable.
