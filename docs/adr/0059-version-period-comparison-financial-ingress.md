# ADR 0059: Version Period Comparison Financial Ingress

- Status: Accepted
- Date: 2026-07-25
- Scope: local exception collection, review-register export, multi-period comparison, and historical comparison compatibility

## Context

Exception CSVs were loaded through pandas type inference before their monetary
fields reached Decimal parsing. Distinct source lexemes could therefore cross a
binary floating-point boundary and become indistinguishable. The fallback
period fingerprint also represented every missing or malformed amount as
`0.00`, which could make a data-quality failure recur as if it were a real zero.

The period-comparison JSON was unversioned and did not bind its results to the
selected financial-input policy, comparison algorithm, input file bytes, or a
deterministic decision digest. Existing direct Python calls and historical JSON
remain compatibility surfaces and cannot be silently relabelled as strict or
verified.

## Decision

1. Give exception collection, review-register construction/export, and period
   comparison an explicit named financial-input policy. Direct Python defaults
   remain warning `legacy-financial-input-v1`; current review/compare CLI and
   demo paths select `strict-financial-input-v2`.
2. Under strict v2, read exception CSV fields as text before validation and
   derive `amount_impact` with Decimal. Invalid values remain absent and period
   fingerprints distinguish `invalid`, `missing`, and a valid rounded zero.
   The explicit legacy reader retains pandas inference and historical
   invalid-as-zero fingerprint behavior.
3. Keep `Review Register` as the first workbook sheet for existing consumers.
   Add `Report Parameters` as the second sheet so current exports identify the
   selected ingress policy without changing the default sheet.
4. Advance current period-comparison JSON to schema v2. Record the policy,
   fixed comparison/rounding/invalid-value policy, and sorted SHA-256 plus byte
   fingerprints for every recognized exception CSV and `review_state.json`.
   Recheck those files after reading and fail before output creation if they
   changed during the comparison.
5. Compute a path-independent `decision_digest` from policy/configuration,
   input file fingerprints, summaries/trends without local paths, and sorted
   category keys. Compute a separate `artifact_digest` over the complete JSON,
   including display paths. Expose the policy and decision digest in the
   workbook, and the policy in HTML and Markdown.
6. Provide a reader that labels historical unversioned JSON as schema v1
   `legacy-unverified`, and verifies current v2 digests. Optional source
   rechecking compares supplied local period directories with the recorded
   fingerprints. Never manufacture missing policy or input provenance for v1.
7. State that the hashes are local content-integrity aids only. They are not a
   signature, audit opinion, compliance certification, or proof that source
   systems are authentic.

## Consequences

- Strict comparison distinguishes amounts on opposite sides of a cent-rounding
  boundary even when pandas legacy inference collapses their high-magnitude
  source values to the same IEEE-754 value.
- A malformed amount cannot silently recur against a valid zero under strict
  v2; its comparison key contains `amount=invalid`.
- Repeated equivalent decisions over identical input bytes have the same
  decision digest after relocating period folders. Artifact digests still
  differ because the human-facing paths differ.
- Existing direct callers retain legacy behavior and historical JSON remains
  readable, but it is explicitly unverified. Existing default Excel readers
  continue to open `Review Register` first.
- The bounded fingerprint uses two fractional digits and `ROUND_HALF_UP` as
  the historical period identity rule. Currency-specific period identity,
  signed artifacts, source-system attestation, and a generalized evidence
  graph remain separate future work.

## Rollback

Retain the v1 reader and explicit legacy policy through the compatibility
window. Do not route current CLI/demo calls back through an implicit default,
remove the review policy sheet, relabel historical JSON, or discard v2 source
fingerprints and digest verification. Any future comparison writer must use a
new schema/algorithm version and preserve v1/v2 readers plus a documented
migration and rollback path.
