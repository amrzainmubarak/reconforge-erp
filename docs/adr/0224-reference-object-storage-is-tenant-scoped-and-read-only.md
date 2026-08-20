# ADR 0224: Reference object storage is tenant-scoped and read-only

- Status: accepted
- Date: 2026-08-02

## Decision

Add a synthetic `reference-object-storage-readonly` connector with an exact
HTTPS egress URL, runtime credential reference, explicit tenant ID, relative
traversal-free key prefix, bounded object count/size, deterministic cursor,
and SHA-256 verification. Use a dedicated `ObjectStorageTransport` protocol
instead of changing the existing immutable `ObjectStoreProtocol`, preserving
all current local/S3 adapters.

The connector is read-only and rejects cross-tenant metadata, keys outside the
prefix, traversal segments, oversized objects, and checksum mismatch. It does
not bundle a cloud SDK or call a provider.

## Consequences

- Object-storage connector behavior is executable with synthetic transports and
  no cloud account.
- IAM, bucket policy, encryption, provider pagination, network retry, and live
  operational evidence remain adapter-specific and unclaimed.
- No write, delete, presigned URL, or write-back path is introduced.

## Rollback

Remove the object connector module, tests, docs, ADR, exports, and manifest
entries. No database or external state is changed.
