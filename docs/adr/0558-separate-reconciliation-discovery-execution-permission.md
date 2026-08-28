# ADR 0558: Separate reconciliation discovery and execution permission

- Status: Accepted
- Date: 2026-08-23
- Scope: PostgreSQL reconciliation worker queue discovery and claim path

## Context

The worker historically used one permission (`match.run`) for both tenant-wide
queue discovery and per-run execution. Amount-bounded execution policies cannot
be evaluated during discovery because the worker has not yet selected a run and
its persisted exposure.

## Decision

Add optional `discovery_policy_permission` to worker settings. When configured,
the worker uses it only for tenant-wide discovery; `policy_permission` remains
the permission required for the run-level tenant and pre-claim scoped checks.
When omitted, the worker explicitly falls back to `policy_permission` to retain
backward compatibility. A secure deployment may therefore grant discovery and
execution as separate service-account permissions.

## Consequences and evidence

The change is additive and has no schema impact. Focused API/worker/policy tests
pass 33/33 with one live PostgreSQL skip, including the exact call sequence
`match.discover`, `match.run`, `match.run`. Service-account provisioning and
fleet-wide rollout remain deployment gates; no production IAM claim is made.

Rollback is a source/config revert, restoring the explicit single-permission
fallback.
