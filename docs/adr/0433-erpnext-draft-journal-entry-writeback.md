# ADR 0433: Add a disabled-by-default ERPNext Journal Entry write-back boundary

- **Date:** 2026-08-07
- **Status:** accepted

## Context

The ERPNext connector now has a bounded read-only GL Entry adapter, while the
write-back SDK only exposed a provider-neutral Bearer transport. ERPNext uses
`token` authorization and its Journal Entry resource can accept a draft
document. A provider-specific payload contract is useful, but mutation must
remain opt-in and human-governed.

## Decision

Add a deterministic ERPNext Journal Entry draft builder and an exact HTTPS
registration for `/api/resource/Journal%20Entry`. Amounts are exact Decimal
text; each line has exactly one positive side; document debit and credit totals
must balance; and `docstatus` is fixed at `0`. Extend the write-back transport
with a backward-compatible `token` credential scheme. The ERPNext registration
is feature-disabled by default and can dispatch only the explicit
`journal-entry.create-draft` operation after the existing maker-checker and
idempotency controls authorize it.

## Verification and boundary

Synthetic tests cover payload determinism, amount and balance rejection,
endpoint hardening, token-header formatting, approval/feature gating, payload
digest binding, acknowledgement binding, and secret non-disclosure. No live
ERPNext tenant, posting, account mapping, provider-version certification,
compensation endpoint, or production readiness claim follows.

## Rollback

Remove the provider-specific builder, transport auth field, tests, docs, and
manifest entries. Existing Bearer registrations retain their previous digest
and runtime behavior.
