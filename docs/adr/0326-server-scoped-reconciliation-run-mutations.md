# ADR 0326: Bind reconciliation run mutations to server execution scope

- Status: accepted
- Date: 2026-08-04

## Decision

The PostgreSQL server-profile reconciliation submit, cooperative cancel, and
requeue routes must re-evaluate the existing compatible permission contract
(`reconciliation.manage` or `match.run`) against the authenticated tenant and
workspace before repository access. A reusable central helper evaluates the
permission set with OR semantics; it does not narrow existing callers to one
permission. Read routes and the local compatibility boundary remain unchanged.

## Rationale

Reconciliation mutations create or change durable financial-control work. The
route dependency already supports two permission alternatives, so a new scope
check must preserve that contract while binding it to the selected hierarchy.
Duplicating policy logic or silently requiring only one permission would create
an authorization drift and a backward-compatibility break.

## Evidence and boundary

Focused route tests cover six mutation invocations (including rejected
submissions), the generic any-permission helper is tested with `match.run`,
and the full local suite remains green. Hosted CI must pass before promotion.
This does not claim distributed worker authorization, universal
route/job/export/UI coverage, federation, live providers, independent HA/DR,
or production IAM assurance.

## Rollback

Remove the any-permission helper, reconciliation calls/tests, this ADR, and
its manifest entry. No data or schema rollback is required.
