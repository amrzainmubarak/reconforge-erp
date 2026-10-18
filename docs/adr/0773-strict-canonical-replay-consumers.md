# ADR 0773: Extend strict canonical-money decoding to replay consumers

- Status: Accepted
- Date: 2026-08-29
- Owners: Financial Integrity / Consolidation / QA

## Context

The additive `Money.from_strict_canonical_dict()` reader now gives replay
verifiers one exact serialization boundary while preserving the compatible
`Money.from_canonical_dict()` reader. Several additional non-posting
consolidation consumers still restored persisted Money through the compatible
reader before rebuilding an artifact. A caller able to recompute an outer
digest could therefore submit a policy-valid but textually normalized amount
or currency and reach the verifier's later reproduction check.

## Decision

Use the strict reader at the persisted-money boundaries for consolidation
translation-result replay, consolidation worksheet replay, the impairment
bridge replay, and intercompany source-line decoding. Keep API request models,
CLI compatibility readers, and other non-replay adapters on the compatible
reader unless their contract explicitly requires producer-byte identity.

Add regression coverage for re-signed padded amount text and retain the
existing closed-schema, digest, arithmetic, and source-line tests. The strict
reader must reject before financial arithmetic or result reproduction can
accept the artifact.

## Consequences and rollback

Canonical producer output is unchanged. Older non-canonical payloads at these
explicit replay boundaries are rejected rather than silently normalized; this
is an intentional integrity tightening for the current schema contract, not a
schema migration or posting change. Compatibility restoration remains
available at its existing boundaries. Rollback is a reversible code,
test, documentation, and manifest revert with no financial-data mutation.
