# ADR 0499: Retain a fresh local MinIO object-storage integrity report

- **Status**: Accepted
- **Date**: 2026-08-10
- **Decision**: Retain a new dated, schema- and digest-bound report from the
  real boto3-backed object-store adapter against the pinned local MinIO image.
  The drill covers normal and Object Lock buckets, scope isolation, immutable
  creation, checksum tamper detection, retention-delete refusal, and cleanup
  without recording credentials or object contents.
- **Rationale**: Earlier reports establish the provider-neutral contract, but a
  fresh run detects image/runtime drift and binds current evidence to the
  adapter and image digest before any hosted publication decision.
- **Verification**: E-662 reports all five invariants true with digest
  `22597553e1833cf7ec8735ee1091f8309d0117997133b56bd9ee7119c27e1d49`; the
  current-report schema test validates the 2026-08-10 artifact.
- **Boundary**: One disposable MinIO process on one host with synthetic
  credentials/bytes. No replication, KMS, cross-site durability, provider
  interoperability, object-store HA/DR, authorized-download, or production-SLO
  claim follows.
- **Rollback**: Remove the dated report, test-list addition, and evidence/docs;
  retain the provider-neutral object-store contract and prior reports.
