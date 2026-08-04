# ADR 0325: Bind master-data mutations to server execution scope

- Status: accepted
- Date: 2026-08-04

## Decision

In the PostgreSQL server profile, currency, organization, legal-entity,
branch, fiscal-period, and period-status mutations must re-evaluate
`master_data.manage` against the authenticated tenant and workspace before the
master-data repository is called. Read-only routes, unsupported workspace
boundaries, and the SQLite compatibility path remain unchanged.

## Rationale

Master data controls the hierarchy consumed by financial posting and close
operations. A role-level permission and database RLS are necessary but do not
prove that the caller is authorized for the selected business scope. Reusing
the central policy helper closes that route-level gap without adding a second
policy engine or changing the PostgreSQL schema.

## Evidence and boundary

The server-profile identity contract records six scoped master-data mutations
and the execution-scope tests cover the granted hierarchy. Hosted CI must
remain green before this evidence is promoted. This does not claim complete
Finance Core parity, federation, universal route/job/export/UI policy
coverage, distributed invalidation, live providers, independent HA/DR, or
production IAM assurance.

## Rollback

Remove the helper calls, focused assertions, this ADR, and its manifest entry.
No data or schema rollback is required.
