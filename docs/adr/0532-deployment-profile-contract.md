# ADR 0532: Keep deployment editions explicit and fail closed

- **Date**: 2026-08-17
- **Status**: In Progress
- **Scope**: `P4-PLAT-001`, global expansion mode readiness

## Context

The product has local, server, air-gapped, identity, queue, object-store, and
write-back controls, but their safe defaults were not represented by one typed
operator contract. Without an explicit contract, a UI or runbook could present
an edition as supported merely because an individual feature exists.

## Decision

Add `reconforge.deployment.profiles` with four immutable edition profiles:
Community, Team, Enterprise, and Regulated. Each profile declares storage,
identity, queue, object-store, network, write-back, air-gap, key-management, and
failure-domain requirements plus a claim boundary. `validate_deployment_profile`
compares these declarations with operator-supplied runtime facts and returns
stable fail-closed finding codes. The CLI exposes the read-only `deployment
profiles` command.

Write-back always requires explicit human approval. The profile module performs
no network, secret, database, or telemetry operation and grants no authorization
by itself.

## Evidence boundary

This slice proves a deterministic configuration contract and CLI rendering only.
It does not provision or verify PostgreSQL, Redis, object storage, KMS/HSM,
identity federation, independent failure domains, RPO/RTO, or production
readiness. Those remain separate evidence-gated tasks.

## Rollback

Remove the deployment package, CLI command, tests, and this ADR together. No
database migration or persisted data is introduced.
