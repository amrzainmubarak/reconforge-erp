# ADR 0259: Write-back approval API is maker-checker

## Decision

Expose `POST /api/v1/connectors/writeback/intents/{intent_id}/approve` behind a separate `connectors.writeback.approve` permission. The route requires tenant/workspace scope, loads the latest immutable proposal, binds approval to a distinct authenticated actor, checks the closed write-back policy, and appends the approved version with optimistic concurrency.

The endpoint never dispatches a provider call. It is a local approval record only; step-up/MFA assurance is recorded in the intent contract and live provider execution remains separately gated.
