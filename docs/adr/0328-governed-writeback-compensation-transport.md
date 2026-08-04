# ADR 0328: Governed write-back compensation transport

- Status: accepted
- Date: 2026-08-04

## Decision

Add an explicit, opt-in compensation operation to the provider-neutral HTTPS
write-back executor. A registration must allow compensation for the original
operation explicitly; the executor derives a separate `compensate.*` operation
header and an idempotency key suffixed with `:compensation`.

The compensation payload is supplied by the caller as a short-lived in-memory
byte string together with its SHA-256 digest. The executor never reuses the
original payload implicitly, persists the compensation payload, or accepts a
provider acknowledgement whose idempotency key does not match the separate
compensation key. Only an intent already in
`compensation_requested` can cross this boundary, and a valid acknowledgement
with `accepted=true` is required before the intent becomes `compensated`.

## Rationale

The domain already models an auditable compensation lifecycle, but the network
adapter previously stopped at the original acknowledgement. Treating a
compensation as an ordinary retry would risk replaying the original financial
mutation. A separate allowlist, payload digest, operation marker, and
idempotency domain make the provider boundary explicit and fail closed.

## Evidence and boundary

Focused tests cover successful compensation, missing allowlist, payload
tampering, separate operation/key headers, transient HTTP/transport retry,
negative provider acknowledgement refusal, and the reusable synthetic
conformance check. This is a provider-neutral transport contract only: no live
ERP/bank provider, compensation business semantics, provider sandbox, secret
vault, or production egress is claimed.

## Rollback

Remove `allowed_compensation_operations`, the executor method, conformance
check, tests, this ADR, and its manifest entry. No database migration is
required; existing registrations default to no compensation capability.
