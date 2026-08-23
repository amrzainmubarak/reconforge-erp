# ADR 0589: Hardened local Docker runtime smoke

## Status

Accepted — 2026-08-23

## Decision

Record a bounded runtime-hardening smoke for the current image. The image must
run as the dedicated non-root `reconforge` user, and the doctor command must
start successfully with a read-only root filesystem, all Linux capabilities
dropped, and `no-new-privileges` enabled.

## Boundary

This is a local container configuration check. It does not replace image CVE
scanning, signature/provenance verification, seccomp review, multi-architecture
testing, Kubernetes/Compose policy, or production deployment assurance.

## Rollback

Remove the dated evidence record and ADR; no runtime or schema migration is
needed.
