# ADR 0566: Verify managed-key custody metadata without handling key material

- Status: Accepted
- Date: 2026-08-23
- Decision owners: Security / Deployment Governance

## Context

The Regulated profile requires customer-managed keys, while current backup and
object-storage drills use operator-held or synthetic keys. Claiming KMS/HSM
custody from those drills would be incorrect. We need a safe contract for
recording the intended custody boundary before a provider-specific runtime gate
exists.

## Decision

Add a closed non-secret managed-key manifest and
`reconforge deployment verify-key-manifest`. It validates provider identity,
key identifier/version, AES-256-GCM purpose, scope, active status, customer
ownership, and a bounded rotation interval, then emits a deterministic digest.
The command never reads key bytes, resolves secrets, contacts a KMS/HSM, or
mutates state. `local-development` remains an allowed evidence provider for
non-regulated contract tests, but does not satisfy regulated readiness by itself.

## Consequences

- Key custody intent can be reviewed and bound to later runtime evidence without
  exposing key material.
- The manifest is not proof of key existence, rotation execution, HSM backing,
  access policy, destruction, or provider availability.
