# ADR 0769: Bind deployment-readiness evidence to exact content

- Status: Accepted
- Date: 2026-08-28
- Owners: Deployment Governance / Security / QA

## Context

The deployment-readiness matrix already required repository-relative evidence
paths, but a path remained valid after the referenced report, contract, or test
changed. That allowed the matrix digest to remain unchanged while its supporting
evidence drifted. File existence is not evidence identity.

## Decision

Add a closed `evidence_digests` manifest to
`docs/execution/DEPLOYMENT_READINESS_MATRIX.v1.yaml`. Every referenced evidence
path must occur exactly once in the manifest and must match a lowercase SHA-256
digest computed from the repository file at load time. Extra digest entries,
missing entries, malformed digests, path escapes, and content mismatches fail
closed before the matrix is exposed by the CLI.

The digest is an integrity and review-binding control, not a signature, proof of
the underlying runtime event, independent assurance, or a production-readiness
claim. Updating an evidence artifact requires intentionally regenerating the
manifest and reviewing the matrix boundary.

## Consequences and rollback

Consumers receive a deterministic matrix whose evidence references are bound to
the exact checked-in bytes. A normal evidence refresh changes both the artifact
and the matrix digest and is visible in review. Rollback is a metadata/code/test
revert; it does not modify deployment state or financial data.
