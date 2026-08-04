# ADR 0327: Bind evidence mutations to server execution scope

- Status: accepted
- Date: 2026-08-04

## Decision

In the PostgreSQL server profile, evidence registration, evidence linking,
evidence requirements, sensitive evidence drill-down, and checksum
verification must re-evaluate their existing `evidence.manage` or
`evidence.verify` permission against the authenticated tenant and workspace
before the evidence repository is called. Local SQLite behavior and ordinary
read routes remain unchanged.

## Rationale

Evidence is the control plane for close, reconciliation, and audit claims.
Tenant RLS plus a role-level permission does not prove that a selected
business hierarchy is authorized. The central scope helper provides that
binding and replaces the former raw permission-set check used by sensitive
drill-down without introducing a second policy path.

## Evidence and boundary

The server evidence contract covers three `evidence.manage` mutations and one
`evidence.verify` mutation, with focused scope assertions. Hosted CI must pass
before promotion. This does not claim complete evidence-plane workspace
persistence, universal route/job/export/UI policy coverage, federation, live
providers, independent HA/DR, or production IAM assurance.

## Rollback

Remove the helper calls, focused assertions, this ADR, and its manifest entry.
No data or schema rollback is required.
