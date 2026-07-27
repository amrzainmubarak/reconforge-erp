# ADR 0026: Tenant-scoped PostgreSQL evidence registry

## Status

Accepted — bounded server capability.

## Context

The local evidence registry already records SHA-256 provenance and can use an
S3-compatible object provider. In server mode, however, evidence metadata was
still outside the PostgreSQL tenant boundary. That made links to close tasks,
controls, and reconciliations difficult to query safely and left verification
state disconnected from the hosted audit/outbox chain.

## Decision

Add PostgreSQL migration `0008_postgres_evidence_registry` with three
tenant-scoped tables:

- `evidence_registry` stores provenance, checksum, storage reference, retention,
  and provider-verification metadata.
- `evidence_links` associates evidence with governed objects without embedding
  domain-specific foreign keys.
- `evidence_requirements` and deterministic coverage queries record what support
  a governed object requires.

Artifact identity fields (checksum, backend, storage tenant, key, and provider
version) are immutable. Evidence records cannot be deleted; operators must
supersede them. Forced RLS policies apply to every table. Repository writes are
caller-transaction-owned and append hash-chain audit plus transactional-outbox
events before commit.

The server API exposes metadata and governance operations but does not accept
arbitrary file bytes or issue download URLs. A trusted object-storage worker is
responsible for upload, malware scanning, provider checksum calculation,
authorized reads, retention enforcement, and restore workflows.

## Consequences

Positive:

- Evidence metadata, links, requirements, and verification state share the
  PostgreSQL tenant boundary with close and ledger-control evidence.
- Failed audit/outbox writes roll back metadata changes with the caller's
  transaction.
- Direct artifact replacement and deletion are rejected by database triggers.
- Local SQLite evidence behavior remains backward compatible.

Trade-offs and remaining work:

- PostgreSQL stores references and integrity metadata, not large artifact bytes.
- The current worker/publisher and object-storage upload pipeline is still an
  explicit deployment integration.
- Shared hosted persistence remains incomplete until reconciliation and the
  remaining domain repositories migrate.

## Validation

- Repository and schema contract tests: `tests/test_postgres_evidence.py`.
- Authenticated server API contract: `tests/test_api_server_evidence.py`.
- Migration chain and offline SQL checks: `tests/test_alembic_postgres.py`.
- Optional non-privileged PostgreSQL RLS test:
  `test_live_postgres_evidence_registry_enforces_tenant_visibility`.
