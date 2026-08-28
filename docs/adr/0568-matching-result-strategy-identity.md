# ADR 0568: Bind matching result evidence to strategy identity

## Status

Accepted — 2026-08-23

## Context

Matching results already carried a manifest digest, input digest, and decision
digest. A digest alone is difficult to interpret when evidence is exported or
replayed across workers: an operator must also know which strategy family and
version produced it. Without explicit identity, a consumer could accidentally
attribute a valid digest to a different strategy release.

## Decision

`MatchingStrategyResult` carries `strategy_id` and `strategy_version` for every
reviewed adapter. Adapter-side replay verification binds those values to the
executing manifest when supplied, while retaining the existing digest checks.
The fields are descriptive evidence and do not authorize posting, write-back,
or production deployment.

## Consequences

- Exported and persisted result evidence is self-attributing.
- Identity/version drift fails closed before adapter output is accepted.
- Existing manifest, input, and decision digest semantics remain unchanged.
- Cross-engine parity, hosted runtime enforcement, and production readiness
  remain separate evidence gates.

## Rollback

Revert the result fields and adapter bindings as one versioned change; no
database migration is required because the change is at the in-memory/worker
contract boundary.
