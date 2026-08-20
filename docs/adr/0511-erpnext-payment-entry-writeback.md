# ADR 0511: Add a disabled-by-default ERPNext Payment Entry write-back boundary

## Context

ReconForge already has a bounded ERPNext Journal Entry draft boundary and a
provider-neutral write-back executor. Payment Entry is a separate ERPNext
resource with different account and amount invariants. Treating it as a
generic payload would permit schema confusion or an accidental posting path.

## Decision

Add `erpnext-payment-writeback-v1` as a provider-specific, disabled-by-default
draft contract. The contract requires HTTPS with an exact
`/api/resource/Payment%20Entry` path, token credentials resolved only at
transport time, deterministic JSON, exact non-negative Decimal amount text, and
exactly one positive paid/received side. `docstatus` is fixed to `0`; no
posting, approval, or source-system mutation occurs in the payload builder.

All provider I/O remains behind the existing write-back policy, maker-checker
lifecycle, idempotency key, bounded retry, acknowledgement digest, and API
replay fences. The test boundary is synthetic and may use a provider-compatible
HTTPS sandbox; it must not be described as live ERPNext interoperability.

## Consequences

- A second ERPNext financial operation has a typed, exact, reviewable contract.
- Invalid zero, dual-positive, negative, non-finite, same-account, or widened
  endpoint inputs fail closed before network I/O.
- Live ERPNext credentials, provider status semantics, posting, compensation,
  production deployment, and statutory accounting remain explicitly open.

## Rollback

Revert the adapter, package exports, tests, manifest entries, and this ADR.
No migration, customer data, credential, or external provider state is changed.
