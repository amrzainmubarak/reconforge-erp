# ADR 0056: Version Synthetic-Generator Financial-Input Policy

- Status: Accepted
- Date: 2026-07-25
- Scope: Synthetic rate ingress, generator manifest, CLI selection, and historical verification

## Context

The exact synthetic generator already removed monetary binary-float arithmetic,
used registered currency precision, and recorded rates, algorithm, registry,
seed, output hashes, and policy/manifest digests in schema-v1. Its Python rate
API intentionally retained finite-float compatibility, but the manifest did not
identify whether legacy-v1 or strict-v2 parsing governed the rates. The CLI
supplied exact text without selecting a named policy.

Synthetic fixtures feed correctness tests, demos, and benchmarks. Their
financial-input provenance must be reproducible even though they are not real
customer records. Existing v1 manifests and CSV bytes must remain verifiable.

## Decision

1. Split exact `RateInput` (`Decimal`, text, integer) from explicit
   `LegacyRateInput` finite-float compatibility.
2. Thread `financial_input_policy` through rate parsing and dataset generation.
   Direct Python calls default to warning legacy-v1; strict-v2 rejects binary
   floats before target creation. Internal generated-money and range parsing
   always use strict-v2 because their inputs are exact by construction.
3. Make the CLI select strict-financial-input-v2 explicitly. Extend the AST
   compatibility perimeter so production calls cannot omit the selection.
4. Advance the current manifest writer from schema v1 to v2. V2 requires
   `policy.financial_input_policy` and binds it into both the policy and manifest
   SHA-256 digests.
5. Keep the verifier and documented schema compatible with v1. V1 has no policy
   field and implies legacy-financial-input-v1; v2 requires a supported policy.
   Cross-version fields are rejected and historical bytes are not relabeled.
6. Preserve `exact-decimal-v1`, six-decimal integer draws, scenario selection,
   currency quantization, CSV bytes for the same canonical rate values and
   inputs, output inventory, and the eight-path Python return contract.

## Consequences

- CLI fixtures record strict-v2; direct-service fixtures record legacy-v1
  unless callers opt into strict-v2. Finite-float service values/results remain
  compatible and now emit the established warning.
- V2 manifest/policy digests intentionally differ from v1 because they bind the
  additional provenance field. CSV byte hashes remain unchanged for equivalent
  canonical inputs.
- A fixed historical v1 manifest validates and verifies. A v1 policy field or a
  v2 manifest without it fails closed.
- No network, telemetry, customer data, currency-policy change, benchmark
  performance claim, or new generator algorithm is introduced.

## Rollback

Retain v1 and v2 verification while either artifact exists. Never add a policy
field to v1, strip it from v2, or recompute one version under the other label.
Reverting the current writer requires a separately versioned migration and
continued v2 verification. Restoring an implicit CLI policy is unsafe.
