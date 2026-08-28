# ADR 0546: Reject negative provider outcomes before acknowledgement

- **Status**: Accepted
- **Date**: 2026-08-22
- **Scope**: E-832 provider-neutral write-back network dispatch and
  idempotency-status recovery

## Context

`WritebackProviderResponse` already carries an explicit `accepted` boolean.
Before E-832, the transport parser validated the response envelope and
idempotency key but allowed `accepted=false` to flow into the original
`dispatch()` and `recover()` state transitions. That could label a rejected or
unaccepted provider outcome as `ACKNOWLEDGED`. Compensation already rejected a
negative response, so the three provider-facing paths were inconsistent.

## Decision

Treat `accepted=false` as a fail-closed transport error in the shared
`_post_and_validate()` path and in recovery response validation. The executor
must not return a `WritebackNetworkDispatch` for that response. The caller
therefore retains the prior immutable state (`DISPATCHED` for the original
operation or `COMPENSATION_REQUESTED` for compensation) and must use a governed
reconciliation decision before any later transition.

The error is safe and non-sensitive:

- `writeback_not_accepted` for the original mutation;
- `writeback_recovery_not_accepted` for idempotency-status recovery;
- `writeback_compensation_not_accepted` for compensation.

No provider response body, credential, payload, or customer data is included
in the exception message.

## Rationale

An acknowledgement is a positive provider outcome bound to the exact
idempotency key. A negative outcome is not evidence of a financial effect and
must never cross the lifecycle boundary merely because its JSON envelope is
well-formed. Leaving the prior state intact preserves auditability and avoids a
false positive while retaining the existing explicit compensation guard.

## Verification

`tests/test_connector_writeback_network.py` covers original dispatch and
status-recovery negative outcomes, asserting that both remain `DISPATCHED` with
no acknowledgement. The existing compensation negative-outcome test remains
green. The focused 46-test connector transport/domain selector passes.

## Compatibility and rollback

This is a fail-closed behavioral correction. Positive provider responses,
idempotency keys, schemas, migrations, APIs, Community mode, and compensation
semantics remain unchanged. A rollback would remove this ADR, manifest entry,
and the two guarded checks, but would knowingly restore the unsafe possibility
of recording a rejected response as an acknowledgement.

## Boundary

The evidence uses injected/synthetic provider responses only. It does not prove
live-provider status semantics, accounting posting, settlement, distributed
delivery, or production recovery objectives.
