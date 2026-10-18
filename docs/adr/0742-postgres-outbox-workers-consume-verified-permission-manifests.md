# ADR 0742: PostgreSQL outbox workers consume verified permission manifests

- Status: Accepted
- Date: 2026-08-28
- Decision owners: ReconForge execution maintainers

## Context

`PostgresOutboxWorker` already had a pre-connection policy check before
claiming outbox events and a second check before publishing them. The worker
could nevertheless be configured with a worker identity and permission names
that were not bound to the reviewed deployment artifact. Reusing one execution
permission for discovery also weakened least privilege. `OutboxWorkerSettings`
is shared with the local SQLite worker, so hosted deployment controls must not
silently expand the local boundary.

## Decision

Policy-supplier-backed PostgreSQL outbox workers must receive a verified
`WorkerPermissionManifest`. The settings must match the manifest's worker ID,
audit principal ID, discovery permission, and execution permission. Missing
manifests and configuration drift fail before database access.

The worker uses the manifest discovery permission for the pre-connection
discovery/claim authorization and the manifest execution permission for the
authorization immediately before publisher and failure-lifecycle side effects.
The existing central policy guard remains authoritative for dynamic tenant,
workspace, organization, and entity scope and can revoke a currently valid
manifest grant. The local SQLite `OutboxWorker` rejects manifest and hosted
discovery configuration rather than treating it as a local policy contract.

## Consequences

- Worker identity and capability names become an explicit, reviewable artifact
  contract.
- Discovery and publishing have separate least-privilege checks.
- The policy supplier still re-evaluates current scope immediately before the
  relevant side effect; a manifest is not a substitute for runtime policy.
- PostgreSQL workers using a supplier must be updated with a manifest. The
  explicit unbound compatibility flag remains a named exception.
- No schema or migration change is required.

## Verification and boundaries

The focused outbox contract suite passes 21/21 with two declared skips when a
live PostgreSQL service is unavailable. It covers missing-manifest
no-connection rejection, configuration drift, discovery/execution separation,
scope propagation, and revocation before publish. This ADR does not claim
external IAM provisioning, universal worker adoption, distributed revocation,
HA/DR, provider behavior, or production authorization effectiveness.

## Rollback

Revert the E-1082 code, tests, manifest entry, and execution records together.
Do not restore per-call permission substitution without a replacement
artifact-binding design and its regression evidence.
