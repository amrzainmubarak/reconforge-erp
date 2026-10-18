# ADR0865: Audit monetary execution scope before owner access

Date: 2026-10-18

Status: Accepted; actual final-source browser/restore acceptance pending.

## Evidence

The mandatory identity browser completes, and the unchanged independent reader
qualifies its raw financial cycle (12 effects,28 lines). Observation verification
refuses at its required persisted scope-denial witness. The actual HTTP403 has
`entity_scope_denied`, but its captured audit suffix contains only allowed policy
decisions. The route's execution-scope grant check refuses before central policy
can persist the denied scoped decision. The negative artifacts remain retained.

## Decision

Allow the existing execution-scope resolver to require an explicit central
permission decision after authentication and header validation, before its grant
checks or any business transaction. Monetary partial-return routes opt in with
their already mandatory `finance_core.read` capability. Existing route-specific
permission dependencies, human/step-up requirements and owner authorization are
unchanged. Other callers retain their current default behavior.

The existing policy sink independently commits redacted decision evidence inside
the authenticated tenant. Do not write a decision into a sibling tenant. Audit
failure retains the existing503 refusal. No financial rows, rules, migrations,
independent-reader acceptance predicates, digests or budgets are changed.

## Verification and rollback

Actual ordinary-role PostgreSQL tests exercise workspace, organization and entity
refusals, persisted bound denial evidence, audit-chain verification and unchanged
89-table business digests. Preserve their initial negative run. Repeat the actual
mandatory identity/foreign HTTPS and populated restore gates on the final source.
Rollback the route's explicit opt-in and resolver parameter together; no database
migration is required. Reverting restores the observed missing audit witness and
must leave that acceptance gate negative.
