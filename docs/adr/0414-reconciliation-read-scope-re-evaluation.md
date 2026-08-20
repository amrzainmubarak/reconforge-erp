# ADR 0414: Re-evaluate reconciliation read routes against the full hierarchy

- **Status:** Accepted
- **Date:** 2026-08-07
- **Scope:** PostgreSQL reconciliation API reads

## Context

The reconciliation API's permission dependencies checked that a caller held a
read-capable permission, but only mutation routes re-evaluated the selected
tenant/workspace scope immediately before the PostgreSQL operation. This left
list, detail, and child-result reads behind the central organization/entity
policy boundary.

## Decision

Add one read-scope guard for run listing, run detail, and inputs/results/
exceptions children. It re-evaluates the any-of set
`reconciliation.read`, `reconciliation.manage`, `match.read`, and `match.run`
against tenant, workspace, optional organization, and optional legal entity
from the authenticated request execution scope. Mutation routes use their
existing narrower manage set but now pass the same optional hierarchy fields.

## Safety and compatibility

- The route-level permission dependency remains the first check.
- Local SQLite compatibility is unchanged; the guard is a no-op outside server
  identity mode.
- PostgreSQL transaction-local RLS already receives the same hierarchy through
  `execute_postgres_reconciliation`; this decision aligns policy and storage
  boundaries rather than adding a second data path.
- No schema or migration is required, and the change is reversible by removing
  the guard calls.

## Evidence boundary

The API route contract proves all eleven read/write calls re-evaluate the exact
tenant/workspace/organization/entity scope in a synthetic server identity
fixture. This does not prove complete route-wide IAM adoption, federation,
distributed revocation, live PostgreSQL availability in this host, HA/DR, or
production readiness.
