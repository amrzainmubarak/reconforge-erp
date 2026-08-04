# ADR 0322: Re-evaluate server scope before close and ownership mutations

- Status: accepted
- Date: 2026-08-04

## Decision

When the PostgreSQL server profile handles a consolidation-close or
consolidation-ownership mutation, the route must re-evaluate the required
finance permission against the authenticated tenant and workspace before
invoking the repository:

- period creation and worksheet preparation require `finance_core.manage`;
- run approval, reversal approval, period lock/reopen, and certification
  review require `finance_core.validate`;
- control-journal posting and reversal requests require their existing
  `finance_core.validate` and `finance_core.manage` boundaries respectively;
- certification preparation and ownership saves require `finance_core.manage`.

The existing local SQLite compatibility path is unchanged. Read routes retain
their existing permission dependency and authenticated workspace binding.

## Rationale

Role membership alone does not prove that a principal may mutate the selected
workspace. The central policy engine already evaluates tenant/workspace
authority and step-up state; applying it immediately before the PostgreSQL
repository boundary prevents a later route or adapter change from widening a
mutation beyond the authenticated hierarchy.

## Evidence and boundary

Focused close, ownership, and execution-scope tests pass with explicit route
adoption assertions. The hosted server-identity fixture remains the runtime
proof for the PostgreSQL branch. This decision does not claim complete
enterprise federation, policy administration, distributed cache invalidation,
or full route/job/export/UI migration.

## Rollback

Remove the scoped-permission calls, their focused assertions, this ADR, and its
manifest entry. No schema migration or data rollback is required.
