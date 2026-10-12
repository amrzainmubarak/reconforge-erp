# ADR 0739: Governed workers consume verified permission manifests

- **Status:** Accepted
- **Date:** 2026-08-28
- **Decision owners:** Platform Security / Runtime Governance

## Context

The repository already had an offline, closed-contract worker permission
manifest verifier. It checked the logical worker identity, service-account
principal, scope text, distinct non-human discovery and execution permissions,
the complete grant set, and a deterministic digest. The opt-in governed durable
worker facade, however, accepted a caller-supplied permission on every claim
and lifecycle call without consuming that verified artifact. A caller could
therefore present a reviewed manifest while substituting another permission or
namespace at runtime.

## Decision

`GovernedDurableJobWorkerService` must be constructed with a verified
`WorkerPermissionManifest`. Before any durable-job repository operation it
binds and checks:

- the logical worker ID against `manifest.worker_id`;
- the policy principal against `manifest.principal_id`;
- the exact canonical tenant/workspace/organization/entity namespace against
  `manifest.scope`; and
- the requested permission against the manifest's non-human
  `execution_permission`.

The separate `discovery_permission` is not accepted by this execution facade.
Discovery remains a separate deployment/queue-enumeration concern. The
backend-neutral `DurableJobWorkerService` remains unchanged so Community and
other explicitly local callers retain their existing compatibility boundary.

## Security and audit consequences

- Permission substitution fails before the repository is touched.
- Worker and principal identity drift fails before claim or lifecycle mutation.
- A leased job is rechecked against the same fixed manifest contract at every
  lifecycle boundary, in addition to the central policy re-evaluation.
- Existing sanitized policy decision audit evidence remains in place; the
  manifest digest is part of the immutable constructor contract rather than
  raw financial or identity data in logs.

## Boundaries

This proves only the opt-in governed facade consumes a locally verified
manifest. It does not provision service accounts, query an external IdP,
prove that production workers use the facade, provide distributed revocation,
or establish HA/DR, provider, or production authorization assurance.

## Compatibility and rollback

The governed facade constructor becomes intentionally stricter; callers must
provide a verified manifest. The raw worker API, database schema, migrations,
and Community compatibility path are unchanged. Roll back by reverting the
E-1079 code, tests, and execution records together. Do not restore unbound
per-call permissions on the governed facade without a replacement binding
contract.

## Verification

- `python -m pytest tests/test_governed_worker_policy.py tests/test_worker_permission_manifest.py -q --tb=short`
  -> 22 passed.
- Full Python/static/security/package/YAML/diff gates are the release evidence
  for E-1079 and must be rerun from the committed slice head.
