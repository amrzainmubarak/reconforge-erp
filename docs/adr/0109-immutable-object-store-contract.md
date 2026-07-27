# ADR-0109: Immutable backend-neutral object-store contract

- Status: Accepted
- Date: 2026-07-27
- Scope: P1-PLAT-005

## Decision

Define one tenant-scoped immutable byte-object protocol and implement it for a
local filesystem and S3-compatible providers. Both adapters reject traversal,
bound object size, prevent overwrite, verify SHA-256 and tenant metadata on
read, disable deletion by default, and enforce configured retention before a
normal delete. Evidence registration and verification consume the protocol.

Keep TLS and server-side encryption enabled by default for S3. Add boto3 to the
locked server extra because the documented server installation must contain
its advertised S3 driver. Register the bounded local sidecar JSON parser in the
closed ingestion inventory.

## Consequences

- Offline evidence can use the same injected object contract as S3-backed
  evidence without changing the registry service.
- Live MinIO verifies conditional creation, tenant separation, tamper
  detection, version-specific deletion, and governance retention behavior.
- The local adapter publishes content and manifest with separate exclusive
  hard-link operations. A crash between them can leave an incomplete pair, which reads fail
  closed; the pair is not claimed to be crash-atomic.
- Local SHA-256 sidecars detect accidental or one-sided modification but do
  not authenticate against an actor able to rewrite both files. No WORM,
  signature, replication, malware-scanning, hosted durability, or compliance
  claim follows from this slice.
