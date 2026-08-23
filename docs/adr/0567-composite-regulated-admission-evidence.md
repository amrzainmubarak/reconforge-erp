# ADR 0567: Compose regulated profile and managed-key evidence before admission

- Status: Accepted
- Date: 2026-08-23
- Decision owners: Deployment Governance / Security

## Context

Separate runtime-profile and managed-key manifests are useful but can be
reviewed independently, allowing a regulated admission process to combine a
complete-looking profile with a local-development key provider or unresolved
failure-domain evidence.

## Decision

Add a closed composite envelope verified by
`reconforge deployment verify-regulated-admission`. It requires regulated
runtime evidence with no profile findings and a non-local customer-managed key
manifest, then emits child digests and a composite digest. The verifier is
offline and does not contact KMS/HSM, resolve secrets, or mutate admission
state.

## Consequences

- Local review and future admission automation receive one deterministic,
  fail-closed evidence object.
- The gate is a prerequisite checker, not proof that the provider exists,
  enforces access policy, rotates keys, or satisfies regulated operations.
