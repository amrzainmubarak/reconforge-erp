# ADR 0222: Write-back is an approved, acknowledged, and compensatable intent

- Status: accepted
- Date: 2026-08-02

## Decision

Add a closed, provider-neutral write-back intent lifecycle. A mutation starts
as `proposed`; an operator feature flag and an allowed operation are required;
a distinct human actor with step-up/MFA assurance must approve it; dispatch is
valid only once from `approved`; acknowledgement must carry the original
idempotency key and a response digest; compensation is a separate explicit
transition with its own idempotency suffix.

The intent contains only a payload digest. Credentials, destinations, raw
payloads, and provider data remain outside this contract. The module performs no
network I/O and the manifest capability model remains read-only until a future
provider-specific write capability is separately designed and reviewed.

## Consequences

- Replay, self-approval, disabled-feature, unsupported-operation, and
  mis-bound-acknowledgement paths fail closed.
- A future adapter has a stable audit/idempotency boundary without pretending
  that a provider acknowledgement or compensation already exists.
- Live ERP/bank providers, signed package admission, secret provisioning,
  provider-specific compensation semantics, and production deployment remain
  open work.

## Rollback

Remove the write-back module, exports, tests, docs, ADR, and package entries.
No database schema or external state is changed by this decision.
