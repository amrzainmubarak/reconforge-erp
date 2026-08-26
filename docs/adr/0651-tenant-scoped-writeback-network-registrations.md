# ADR 0651: Bind server write-back registrations to tenant and workspace

## Status

Accepted — 2026-08-26

## Context

Server write-back intents already carry a tenant and workspace, and the HTTP
routes re-evaluate permissions for that scope. The in-memory
`WritebackNetworkRegistration` registry was keyed only by `connector_id`,
however. A globally configured registration could therefore be selected for a
different authenticated scope if the deployment supplied the same connector
identifier to both scopes. That is unsafe because the registration also names
the endpoint and credential reference.

## Decision

Add optional tenant/workspace binding fields to the version-1 registration
contract, requiring both fields together. Any server route must select a
registration with an exact tenant/workspace match. The network executor repeats
the same check as a defense-in-depth boundary and rejects both unbound and
cross-scope registrations before payload or secret resolution and before
provider I/O. The registration scope is included in its digest when bound.

The fields remain optional at construction time so local SDK configuration and
legacy read-only inspection can continue to parse old registrations. They are
not executable: dispatch, recovery, observation, and compensation all fail
closed until a server registration is explicitly bound.

## Compatibility and rollback

This is an additive model change. Existing local SQLite intent behavior and
non-executing registration inspection remain compatible. Server deployments
must update each admitted registration with its exact tenant/workspace pair;
an unbound registration now returns a safe configuration error. Rollback is a
code revert, after restoring any registration configuration that was updated to
the additive fields. No database migration is required.

## Boundary

This decision proves application-level scope binding for the configured
write-back boundary. It does not prove provider interoperability, credential
vault correctness, distributed registry consistency, accounting posting,
cross-host HA/DR, or production readiness.
