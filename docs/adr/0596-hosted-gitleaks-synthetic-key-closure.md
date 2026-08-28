# ADR 0596: Close the hosted synthetic writeback-key finding

## Status

Accepted — 2026-08-23

## Decision

Replace the current-tree synthetic writeback idempotency value flagged by the
hosted scanner with the neutral token `synthetic-recovery-idempotency`. Retain only the eight exact immutable
historical Gitleaks fingerprints reported by hosted run `32642926377` in
`.gitleaksignore`.

## Boundary

The finding was a deterministic `generic-api-key` false positive; no live
credential was exposed. The current tree and full history are scanned locally
with Gitleaks 8.30.1 and the configured default rules. This does not replace
credential rotation or hosted security attestation when a real secret is ever
found.

## Rollback

Revert the neutral-token/documentation changes and exact fingerprints together
if the synthetic fixture contract is intentionally restored. No runtime or
schema migration is involved.
