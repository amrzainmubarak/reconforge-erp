# ADR 0054: Version Anonymizer Financial-Input Policy

- Status: Accepted
- Date: 2026-07-25
- Scope: Amount-noise policy ingress, amount masking, and shareable manifest

## Context

The anonymizer changes financial values when amount masking is enabled. Its CLI
already accepted exact decimal text, but the service parser, factor cache, and
cell masker inherited legacy-v1 behavior. The schema-v1 manifest recorded the
canonical percentage and algorithm but not whether a binary float had been
accepted before that text existed.

Unlike an ephemeral filter, anonymized output is a durable artifact. Selecting
strict behavior only in code without recording the selected parser policy would
make the output policy incomplete. Existing checked-in and user-produced v1
manifests must remain verifiable.

## Decision

1. Split exact `AmountNoiseInput` from `LegacyAmountNoiseInput`, and pass a
   named financial-input policy through percentage parsing, factor caching,
   frame masking, source-cell parsing, and directory anonymization.
2. Keep direct Python service defaults legacy-v1 for compatibility. Finite
   binary-float percentage input warns; strict v2 rejects it before the output
   directory is created.
3. Make the CLI select strict-financial-input-v2 explicitly. An AST regression
   rejects any production `anonymize_directory` call without a policy.
4. Advance the current manifest writer to schema v2 and include
   `financial_input_policy` in its policy digest. Schema/verifier v1 remains a
   closed historical reader and implies legacy-v1; v2 requires one of the two
   supported policy identifiers.
5. Preserve the amount-noise algorithm, deterministic PRNG/factor scale,
   source-scale rounding, output checksums, privacy boundary, and private-map
   controls. This versions ingress provenance, not masking realism or privacy
   assurance.

## Consequences

- Same exact inputs, seed, profile, and selected policy reproduce the same
  amounts and bytes; v2 policy/manifest digests intentionally include the new
  policy field.
- Existing v1 manifests and the checked-in anonymized example remain valid and
  are labeled legacy by definition. They are not rewritten in place.
- New direct service calls still default to legacy but disclose that fact in a
  v2 manifest. New CLI outputs disclose strict v2.
- No network, telemetry, cloud upload, new reversible mapping, or write-back is
  introduced.

## Rollback

Never relabel a v2 manifest as v1 or remove its policy field without restoring
the matching historical bytes/digests. Keep the v1 verifier while supported
artifacts exist. Reverting the current writer requires an explicit schema
migration and preservation of v2 verification; silently dropping ingress policy
from durable evidence is unsafe.
