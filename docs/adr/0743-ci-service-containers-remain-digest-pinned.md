# ADR 0743: Keep CI service containers digest-pinned

- Status: Accepted
- Date: 2026-08-28
- Decision owners: supply-chain and release maintainers

## Context

The server-boundary CI job depends on PostgreSQL and Redis service containers.
A tag is a human-readable label, not an immutable execution identity. The
workflow already used exact image digests, but the tracked dependency-risk and
gap documents incorrectly described those services as mutable tag-only inputs.
That mismatch could hide future drift and made the release record less useful.

## Decision

Keep the reviewed service identities explicit in `.github/workflows/ci.yml`:

- PostgreSQL 16 Alpine:
  `postgres:16-alpine@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777`
- Redis 7.4 Alpine:
  `redis:7.4-alpine@sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2`

The Redis digest passed to the live-report verifier must remain the digest
portion of the configured Redis image. Reviewed image updates must change the
version label and digest together and retain fresh runtime evidence.

## Consequences and boundaries

Digest pinning makes the selected image bytes stable for the reviewed workflow
and prevents tag movement from silently changing a run. It does not
authenticate provenance, establish freshness or vulnerability status, prove
license suitability, provide independent PostgreSQL/Redis assurance, prove
hosted execution, or establish production readiness.

## Verification and rollback

`tests/test_phase4_execution_contract.py` asserts both exact image references,
the single-digest form, and Redis live-report subject binding. Existing
supply-chain and Redis live-report tests remain part of the regression set.
Rollback consists of reverting the documentation/test/ADR changes and the
corresponding reviewed image update, if any; no database migration is involved.
