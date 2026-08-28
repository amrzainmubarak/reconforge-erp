# ADR 0593: Enforce the hardened container smoke in CI

## Status

Accepted — 2026-08-23

## Decision

Extend the required `docker-parity` CI job with the same bounded runtime smoke
used by the local Docker evidence: read-only root filesystem, all Linux
capabilities dropped, and `no-new-privileges`, followed by `reconforge doctor`.
The ordinary doctor, sample-data validation, and control-pack validation remain
separate checks so a hardened-runtime regression is attributable.

## Boundary

This verifies the image's declared local hardening contract on the GitHub Linux
runner. It does not prove seccomp policy completeness, multi-architecture
parity, host isolation, registry provenance, or production orchestration.

## Rollback

Remove the additional CI command and this ADR. No runtime, schema, or data
migration is involved.
