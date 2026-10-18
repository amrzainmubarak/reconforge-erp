# ADR 0657: Reject hosted policy configuration in the local outbox worker

- Status: accepted
- Date: 2026-08-26
- Scope: Local SQLite transactional-outbox worker construction

## Context

`OutboxWorkerSettings` is shared by the local SQLite `OutboxWorker` and the
tenant-scoped `PostgresOutboxWorker`. The hosted worker understands service
identity, hierarchy scope, and central-policy suppliers. The local worker does
not have a tenant lane or a server authorization boundary. Before this ADR, a
caller could pass hosted policy or scope settings to the local worker and the
settings would be silently ignored.

Silent authorization configuration loss is unsafe: it can turn an operator's
intended governed deployment into an ungoverned local delivery process without
an explicit failure.

## Decision

The local `OutboxWorker` rejects any hosted-policy or scope configuration at
construction time, including an actor override, policy supplier, scope
supplier, or non-default policy permission. The error directs the caller to
`PostgresOutboxWorker`, which is the worker that implements the tenant,
hierarchy, service-account, and central-policy boundary.

The default local configuration remains unchanged. Community/local workers
continue to process the SQLite outbox without a central policy supplier. No
SQLite schema, event format, or delivery lifecycle changes are introduced.

## Evidence and limits

The regression test proves that an unsupported hosted-policy configuration is
rejected before the local connection factory is invoked. PostgreSQL outbox
policy tests continue to cover the supported hosted path. This does not prove
external IAM, distributed policy invalidation, broker delivery semantics,
provider behavior, HA/DR, or production authorization effectiveness.

## Rollback

Revert the constructor guard, its regression test, and this documentation. No
database or external-state rollback is required.
