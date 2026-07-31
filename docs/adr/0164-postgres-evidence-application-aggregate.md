# ADR 0164: Contract-compatible PostgreSQL evidence-registry aggregate

## Status

Accepted — 2026-07-28

## Context

The historical PostgreSQL evidence repository is tenant-scoped and accepts
caller-supplied checksums and external references. The eight-operation Evidence
Application port is workspace-scoped, owns local-file hashing, optionally writes
through the object-store port, and exposes bounded relationship drill-down.
Fabricating workspace scope or weakening the existing tenant-wide uniqueness
would create cross-workspace ambiguity and risk breaking the legacy API.

## Decision

Add migration 0031 with separate tenant/workspace registry, append-only link,
and requirement tables under forced RLS. Preserve migration 0008 and the legacy
repository unchanged. The new adapter implements all eight Application
signatures, hashes source bytes locally, verifies provider-returned bytes and
tenant metadata, rejects artifact rebinding, stores no raw artifact bytes in
PostgreSQL, and commits registry/link/requirement audit effects in the same
database transaction.

Evidence identity is immutable; an existing code may update governance metadata
only when checksum, source path, storage backend, tenant, and key are unchanged.
Object identity is checked before upload so retries are idempotent and a rejected
rebind cannot overwrite a caller-selected object key. Links are append-only.
Reads, coverage, reverse-link expansion, depth, nodes, pagination, and offsets
are bounded. Sensitive storage and checksum fields are redacted unless the
caller explicitly requests them.

## Consequences

The additive aggregate avoids a breaking schema migration and makes the two
contracts explicit. A database commit can still fail after a successful new
object upload; operators must use content-addressed keys and lifecycle cleanup
for orphan candidates. PostgreSQL current-live behavior remains unclaimed until
the optional non-superuser lifecycle/RLS test runs against a configured service.
