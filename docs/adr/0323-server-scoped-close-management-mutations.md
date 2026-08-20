# ADR 0323: Bind close-management mutations to server execution scope

- Status: accepted
- Date: 2026-08-04

## Decision

The PostgreSQL server-profile close-management mutations must re-evaluate
`close.manage` against the authenticated tenant and workspace before invoking
the close repository. This applies to period initialization, task status
changes, period lock, and period reopen. Read-only period/task/readiness routes
and the local SQLite compatibility path remain unchanged.

## Rationale

The close-control repository already runs inside transaction-local PostgreSQL
RLS, but the route's role dependency did not independently bind the mutation
permission to the selected hierarchy. Reusing the central policy helper closes
that gap without introducing a second authorization model or changing the
close schema.

## Evidence and boundary

The server-profile API contract records the scoped permission call before both
write operations exercised by the fake runtime, while execution-scope tests
cover sibling denial and granted access. Hosted PostgreSQL server-identity CI
is required before promoting the runtime evidence. This does not claim full
route/job/export/UI policy adoption, federation, distributed invalidation,
live provider operation, HA/DR, or production IAM assurance.

## Rollback

Remove the four helper calls, focused assertions, this ADR, and its manifest
entry. No data or schema rollback is required.
