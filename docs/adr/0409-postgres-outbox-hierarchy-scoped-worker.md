# ADR 0409: PostgreSQL outbox hierarchy-scoped worker

- **Date**: 2026-08-06
- **Status**: Accepted

## Context

The PostgreSQL transactional outbox already enforced tenant RLS, but a hosted
publisher lane could still claim events across workspaces, organizations, or
legal entities inside one tenant. Scheduler and reconciliation workers now
carry their persisted hierarchy, so outbox delivery must use the same boundary
without breaking legacy tenant-wide callers.

## Decision

Migration `0073_pg_outbox_scope` adds nullable `workspace_id`,
`organization_id`, and `legal_entity_id` columns to `outbox_events`, with
transaction-local defaults, a scope-aware pending index, and an explicit RLS
policy. Existing rows remain readable as legacy tenant-scoped events. The
repository accepts optional scope predicates in its atomic `FOR UPDATE SKIP
LOCKED` claim query and returns the hierarchy for verification.

`PostgresOutboxWorker` accepts deterministic four-part lanes
`(tenant, workspace, organization, legal_entity)`. Each lane is validated and
policy-authorized before connection access. Organization scope uses a separate
four-argument policy supplier and is also part of the central ABAC context and
cache invalidation key; a three-argument workspace/entity supplier cannot
silently authorize an organization lane. Every claim, publish, and failure
transaction restores the exact PostgreSQL transaction scope. A legal entity
requires an organization. A scoped event whose returned attribution does not
match its lane fails closed. Tenant-only suppliers remain compatible for
legacy events and deployments.

## Verification and boundary

Focused outbox, worker, migration, and policy contracts cover additive tuple
compatibility, exact claim parameters, policy-before-connection behavior,
transaction-local GUC propagation, event-lane mismatch refusal, and migration
reversibility. This is local/static evidence plus capability-gated PostgreSQL
tests; it is not proof of live provider delivery, distributed queue fairness,
HA/DR, throughput, or production readiness.

## Reversibility

Downgrade removes the scope index and columns and restores the tenant-only
policy. Removing the optional worker suppliers and repository filters leaves
existing tenant-only outbox events and publisher contracts intact.
