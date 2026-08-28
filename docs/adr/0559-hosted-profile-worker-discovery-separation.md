# ADR 0559: Require worker discovery separation in hosted deployment profiles

- Status: Accepted
- Date: 2026-08-23
- Scope: Deployment profile validation and reconciliation worker governance

## Context

E-844 added an optional least-privilege discovery permission to reconciliation
workers. Without a deployment-profile requirement, a Team, Enterprise, or
Regulated operator could omit it while still treating the profile as valid.

## Decision

Add `requires_worker_discovery_execution_separation` to immutable profiles and
`worker_discovery_execution_separation_verified` to runtime facts. Team,
Enterprise, and Regulated validation returns
`worker_discovery_execution_separation_required` until the fact is true.
Community remains exempt because it does not use the hosted worker topology.

## Consequences and evidence

The contract is descriptive and fail-closed; it performs no provisioning or
network operation. Profile tests pass 9/9 with Ruff and Mypy. The finding is a
deployment gate, not evidence that service accounts, IAM, or a production fleet
have been configured.

Rollback is an additive source revert with no schema impact.
