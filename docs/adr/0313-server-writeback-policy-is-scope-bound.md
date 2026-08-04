# ADR 0313: Server write-back authorization is bound to the execution scope

- Status: accepted
- Date: 2026-08-04
- Decision owners: ReconForge maintainers

## Context

The server-profile write-back routes already required a named permission and
checked that the submitted tenant/workspace matched the request headers. That
left the central policy decision itself without the selected hierarchy. A
future route or adapter could therefore pass the coarse permission dependency
while omitting the workspace/entity attributes from the policy evaluation.

## Decision

Keep the existing permission dependency and add an explicit
`enforce_server_scoped_permission` boundary before each PostgreSQL write-back
repository operation. The boundary re-evaluates the same permission with the
authenticated principal, tenant, workspace, optional entity, step-up state,
and durable scope grants. It emits the existing sanitized authorization record
and fails closed with stable scope/assurance codes. Local SQLite compatibility
routes are unchanged.

## Evidence and limits

Focused API execution-scope and write-back tests pass, including sibling
workspace denial before repository use and granted-workspace approval with
step-up. This proves one sensitive server surface is scope-bound; it does not
complete route/job/export/UI migration, federation, distributed IAM assurance,
live ERP/bank interoperability, network write-back, or production readiness.

## Rollback

Revert the helper, the three connector-route calls, tests, this ADR, and the
execution-ledger entries. Existing coarse permission and header equality checks
remain available, but the added server-scope policy gate is removed.
