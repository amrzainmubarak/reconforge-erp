# ADR 0016: Optional S3-Compatible Object Storage

- Status: Accepted; bounded evidence-registry integration implemented
- Date: 2026-07-23
- Decision owners: ReconForge maintainers

## Context

Local evidence folders are useful for inspection and offline operation, but a
server deployment needs durable artifact storage with tenant isolation,
integrity verification, bounded downloads, retention controls, and a path to
versioning and backup policy.

## Decision

Add an optional boto3-backed `S3ObjectStore` supporting AWS S3 and compatible
providers, and make it available to the evidence registry through an explicit
injected contract. Endpoints require HTTPS by default. Every key is constructed as
`<prefix>/tenant/<validated-tenant>/<relative-object-name>`; absolute paths,
traversal segments, and control characters are rejected.

Uploads record a SHA-256 digest in reserved metadata and downloads recompute and
verify it. The adapter supports server-side encryption (`AES256` by default),
optional S3 Object Lock retention when an explicit `GOVERNANCE` or `COMPLIANCE`
mode is configured, bounded presigned GET URLs, and deletion disabled by
default. Provider credentials are intentionally not stored in settings; boto3
credential-chain configuration remains a deployment concern.

## Consequences

- Local filesystem evidence remains the default and is not silently replaced.
- The evidence registry can now upload and verify object-backed records through
  this contract, while local files remain the default and report/worker/API
  artifact lifecycles are not implicitly converted.
- A registry row is committed only after the provider returns matching content
  and checksum metadata. External storage and the local DB are not one atomic
  transaction; content-addressed default keys make retries idempotent, while
  unreferenced objects require provider lifecycle/cleanup policy.
- Bucket versioning, object-lock bucket configuration, KMS policy, malware
  scanning, lifecycle retention, backup replication, and signed-URL
  authorization must be verified in the deployment profile.
- A failed checksum is an integrity error, not a warning that callers may ignore.

## Rejected alternatives

- Storing remote URLs without content checksums: this would not prove the bytes
  reviewed are the bytes later retrieved.
- Reusing local filesystem paths as object keys: this leaks host layout and can
  permit traversal ambiguity.
- Enabling destructive deletion by default: evidence retention needs explicit
  operational approval.
