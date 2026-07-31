# ADR 0190: Schema Installers Preserve Composed RLS

- Status: Accepted
- Date: 2026-07-29
- Decision owners: ReconForge maintainers
- Scope: PostgreSQL application-schema installers at migration head 0044 and later

## Context

PostgreSQL combines permissive row-level-security policies with `OR`. The 0044-0045 migrations replace tenant-only policies with composed workspace, organization, legal-entity, branch, and parent-derived `tenant_scope` policies. Twelve compatibility installers could later recreate a tenant-only `tenant_isolation` policy beside the composed policy. That second policy made the stronger workspace predicate ineffective and caused isolation to depend on schema-installation order.

## Decision

Every current business schema installer must:

1. enable and force RLS as before;
2. drop any compatibility `tenant_isolation` policy;
3. create the tenant-only compatibility policy only when no migrated `tenant_scope` policy exists; and
4. leave an existing composed `tenant_scope` policy unchanged.

A static regression covers all current installers. A live PostgreSQL regression reapplies every installer at head and requires zero tables to carry both `tenant_scope` and `tenant_isolation`.

## Consequences

- Standalone/pre-0044 schema installation retains tenant-only compatibility.
- Reinstalling application schemas at the current head cannot widen workspace or entity visibility.
- New schema installers that create tenant-only policies must join the same regression inventory.
- This does not replace migrations or authorize runtime schema mutation in production.

## Alternatives rejected

- Marking every migrated policy `RESTRICTIVE`: this changes policy composition semantics across the whole schema and requires a separate compatibility migration.
- A database event trigger that blocks policy DDL: it requires elevated capabilities that are unsuitable for many managed PostgreSQL deployments.
- Removing installers immediately: existing tests and compatibility setup paths still rely on them.

## Rollback

The installer guards can be reverted only for a deployment whose schema predates composed RLS. Reintroducing tenant-only policies beside `tenant_scope` at 0044 or later is an isolation regression and is not an acceptable rollback.
