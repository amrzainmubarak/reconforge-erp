# ADR 0560: Verify worker permission manifests offline and digest-bound

- Status: Accepted
- Date: 2026-08-23
- Scope: Hosted reconciliation worker deployment evidence

## Context

E-845 made worker discovery/execution separation a hosted deployment gate, but
an operator-provided boolean could be inaccurate or drift from the intended
service-account grants.

## Decision

Provide `verify_worker_permission_manifest` for a closed JSON-shaped mapping.
It validates worker/principal identity syntax, scope, distinct non-human
discovery and execution permissions, complete sorted grants, rejects unknown
fields, and exposes a canonical SHA-256 digest. The verifier is pure and
network-free; it does not provision accounts or query an identity provider.

## Consequences and evidence

The verified manifest digest can be attached to a deployment runtime fact or
release evidence record. Focused manifest/profile tests pass 15/15 with Ruff and
Mypy. The result proves only local manifest integrity; it does not prove that an
identity provider or production service account matches the manifest until an
independent provisioning/runtime check consumes it.

Rollback is a source revert with no schema or IAM impact.
