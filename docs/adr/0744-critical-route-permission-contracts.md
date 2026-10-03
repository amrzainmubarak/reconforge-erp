# ADR 0744: Freeze critical financial route permission contracts

- Status: Accepted
- Date: 2026-08-28
- Decision owners: identity-governance and financial-control maintainers

## Context

The API already required authorization dependencies and server-scope
re-evaluation, but a future change could replace a high-risk route's exact
permission with a broader capability while leaving the route technically
"protected". That would weaken least privilege and maker-checker review
without necessarily breaking a generic route-inventory test.

## Decision

Maintain a central reviewed contract for selected critical financial-control
mutations. Each entry binds the HTTP method and route template to its exact
authorization mode and sorted permission tuple. The validator rejects a mode
or permission mismatch. Full application construction also requires every
critical entry to be registered, so accidental route removal or renaming fails
closed before serving the application.

The selected set covers account reconciliation lifecycle, close period/task
mutations, reconciliation run lifecycle, connector write-back lifecycle,
finance-entry validation/void, inventory posting/void, consolidation close
approval/posting/reversal, evidence verification, and emergency-access
request/review mutations.

## Consequences and boundaries

This creates an executable least-privilege regression fence at the API
assembly boundary and makes permission changes review-visible. It does not
replace request-time RBAC/ABAC evaluation, server hierarchy checks, SoD
guards, database RLS, external identity-provider enforcement, distributed
revocation, or production authorization assurance. The selected set is
deliberate rather than a claim that every future domain action has been
independently reviewed.

## Verification and rollback

`tests/test_api_authorization_inventory.py` proves full application inventory
construction and rejects a tampered finance-validation permission contract.
The existing API dependency, server-identity, route-boundary, and full
regression suites remain required. Rollback is a source-level revert of the
validator, tests, documentation, and ADR; no database migration is involved.
