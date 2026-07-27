# ADR 0094: Deny by default and prohibit ordinary self-approval overrides

- Status: Accepted
- Date: 2026-07-27
- Decision owners: Identity Security, Financial Controls, Platform Architecture
- Scope: P0-SEC-010 authorization-policy primitive and current platform approval/review services

## Context

The central policy engine granted an authenticated identity when a caller named
no permission contract, and its tenant/workspace fields did not enforce scope.
Entity and period scope were absent. Ownership checks were opt-in. Separately,
the generic approval service allowed a requester to approve the same request by
supplying arbitrary `override_reason`; trusted-local workflow labels and several
local approval services could also bypass creator checks because no database
user resolved or because the actor was `local-cli`.

These paths contradicted the Phase 0 exit rule that deny-by-default,
tenant/entity/period restrictions, and no-self-approval behavior hold under
generated tests.

## Decision

- `CentralPolicyEngine.evaluate` requires a named permission. Identity or an
  unrelated permission never grants access.
- Every supplied tenant, workspace, entity, and period resource identifier must
  be present in the corresponding immutable authorized-ID set. Missing grants
  deny scoped access. Ownership enforcement defaults on for approve/review.
- Use one non-empty, trimmed, case-folded `same_actor` primitive across the exact
  current platform approval/review surface inventory.
- A requester may not approve their own generic request. `override_reason` is
  retained only as a deprecated compatibility option and now fails visibly;
  it never authorizes a decision. A requester may reject/withdraw their own
  request with the existing required reason because rejection creates no
  positive financial approval.
- Apply creator/preparer checks to trusted-local labels as well as database
  users for AP purchase orders/invoices, AR invoices, account review, inventory
  counts, valuation, valuation reversal, certification, and generic approvals.
- Workflow SoD derives a stable label identity when no local user exists, so
  case/outer-whitespace variants cannot bypass prior-action conflict checks.
- Maintain an exact AST inventory of every platform service method beginning
  with `approve` or `review`; a new surface fails until its SoD policy is explicit.

## Evidence and limitations

Hypothesis exercises all four scope dimensions and creator approve/review
actions. Integration tests cover generic override refusal, trusted-local
workflow labels, trusted-local AP creator refusal, AR creator refusal with a
credit override, and the established account/inventory/user-backed paths.

This is a bounded local policy foundation, not complete ABAC integration across
every API/repository, privileged emergency access, amount/region/data-class
policy, centralized assignment delegation, enterprise identity governance, or
deployed operating-effectiveness evidence. Trusted-local mode still bypasses
RBAC for local-only use, but it no longer bypasses the inventoried SoD checks.

## Compatibility and rollback

Valid distinct-actor approvals remain unchanged. Self-approval and any non-empty
generic approval `override_reason` now fail; this intentional security tightening
may require local scripts to pass distinct actor labels. The CLI option remains
parseable with a deprecation message, avoiding an option-removal break.

Rollback the engine, shared actor comparator, service guards, CLI wording,
tests, inventory, and governance together. Do not restore arbitrary override
text as approval authority. If emergency access is later required, implement a
separate time-bound, strongly authenticated, independently reviewed workflow.
