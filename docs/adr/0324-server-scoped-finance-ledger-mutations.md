# ADR 0324: Bind finance-ledger mutations to server execution scope

- Status: accepted
- Date: 2026-08-04

## Decision

In the PostgreSQL server profile, account upsert and atomic ledger-entry
creation must re-evaluate `finance_core.manage` against the authenticated
tenant and workspace before the ledger repository is called. Read-only ledger
routes, unsupported local/server feature boundaries, and the SQLite
compatibility path remain unchanged.

## Rationale

These operations mutate financial control data. A global role permission and
database RLS are necessary but do not by themselves provide route-level proof
that the caller's selected hierarchy is authorized. The existing central
policy helper supplies that proof without accepting a new amount or entity
scope model in this bounded slice.

## Evidence and boundary

The server-profile identity contract records three scoped finance mutations
(two account upserts and one ledger entry) and execution-scope tests cover
granted/sibling outcomes. Hosted CI must remain green before the evidence is
promoted. This does not claim full finance-core feature parity, statutory
posting, complete route/job/export/UI policy coverage, federation,
distributed invalidation, live providers, HA/DR, or production IAM assurance.

## Rollback

Remove the two helper calls, focused assertions, this ADR, and its manifest
entry. No data or schema rollback is required.
