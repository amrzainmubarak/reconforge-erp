# ADR 0422: Refuse hierarchy-attribution loss during PostgreSQL downgrades

- **Status**: accepted
- **Date**: 2026-08-07
- **Scope**: PostgreSQL hierarchy migrations `0072`, `0073`, `0075`, `0076`, and `0077`

## Context

Several additive PostgreSQL migrations introduced workspace, organization, or
legal-entity attribution. Their downgrade paths removed those columns without
checking whether an installed database already contained attributed rows. That
would make an otherwise reversible migration silently destroy scope lineage.

## Decision

Before any downgrade drops hierarchy-attribution columns, execute a database
side `DO` guard that refuses when at least one affected row has a non-NULL
attribution. The guard runs before policy, index, constraint, default, or column
changes. Empty/legacy-only tables retain the previous downgrade behavior.

The guard is applied to reconciliation runs, transactional outbox events,
durable jobs, PPA artifacts, impairment artifacts, and deferred-tax artifacts.
The migration chain remains linear and no data is copied or rewritten.

## Verification and boundary

Static migration contracts assert every refusal message and the full local
regression/static/package gates must remain green. A live PostgreSQL downgrade
drill is still required before promoting runtime evidence. This decision does
not establish statutory accounting, provider write-back, HA/DR, or production
readiness.

## Rollback

Revert the unpublished migration-file edits and associated contract/docs
changes. No GitHub publication or irreversible database operation is performed
by this slice.
