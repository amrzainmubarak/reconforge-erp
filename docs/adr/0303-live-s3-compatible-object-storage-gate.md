# ADR 0303: Exercise the S3-compatible boundary against disposable MinIO

- Status: accepted
- Date: 2026-08-04
- Scope: `P4-CON-001`, `P4-REL-001` object-store dependency boundary

## Decision

Add an independent CI job that starts a digest-pinned MinIO process with
synthetic credentials, creates one normal bucket and one object-lock bucket,
and runs the existing S3 adapter against the real HTTP endpoint. The job also
runs `verify_s3_object_storage_live.py`, which emits a digest-bound report and
uploads it as a CI artifact.

The gate proves only the adapter/provider contract for hierarchical scope,
immutable create, checksum tamper refusal, object-lock delete refusal, and
cleanup. It does not replace the local-first default or turn the provider into
a mandatory network dependency.

## Rationale

Transport-injected connector tests cannot expose provider-specific behavior
such as conditional creation, object-lock retention, or response metadata
handling. A disposable open-source MinIO process supplies a reproducible
provider test without using customer data, credentials, or a cloud account.
The image is pinned by a full digest and the report excludes secrets and
object bytes.

## Evidence boundary

The runtime profile is a single MinIO process on one CI host with synthetic
objects and credentials. It does not prove replication, KMS/customer-managed
keys, cross-site durability, provider interoperability, object-store HA/DR,
malware scanning, authorized download workflows, or production SLOs.

## Rollback

Remove the object-storage job, verifier, schema, tests, ADR, report upload,
and execution records. The S3 adapter and local filesystem default remain
unchanged; the disposable container is removed in an `always()` cleanup step.
