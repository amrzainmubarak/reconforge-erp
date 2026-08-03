# ADR 0260: Provider acknowledgement reconciliation API

- Status: accepted
- Date: 2026-08-03

## Context

The local write-back lifecycle now has proposal, maker-checker approval, and a
provider-neutral dispatch state. Acknowledgement must be auditable without
turning the API into an implicit network client or allowing an unbound provider
response to mutate another tenant's intent.

## Decision

Add migration 30 and the separate `connectors.writeback.reconcile` permission.
The route accepts only a tenant/workspace-scoped latest intent already in the
`dispatched` state. It requires the original idempotency key, records provider
reference and response digest through the existing deterministic lifecycle
invariant, and appends the result using optimistic versioning. The route has no
provider transport dependency and always reports network dispatch as disabled.

## Consequences

Acknowledgement and rejection are immutable, replayable local evidence with
clear tenant boundaries. Live provider credentials, settlement interpretation,
retry/compensation policy, and production deployment remain separate gates.
