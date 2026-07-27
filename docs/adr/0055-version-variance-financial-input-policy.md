# ADR 0055: Version Variance Financial-Input Policy

- Status: Accepted
- Date: 2026-07-25
- Scope: Variance threshold ingress, policy digest, report writer, and compatibility readers

## Context

Variance report v2 corrected binary-float decision drift by preserving exact
threshold text, comparing unrounded `Decimal` values, and recording a canonical
threshold-policy digest. Its direct Python service nevertheless retained
finite-float compatibility without recording whether legacy-v1 or strict-v2
parsing governed a generated report. The current CLI happened to supply text,
but selected no named policy.

Because threshold values can change which variances are flagged, parser policy
is part of durable decision provenance. Historical unversioned/v1 and v2
reports must remain readable with their original bytes and digests.

## Decision

1. Split exact `ThresholdInput` (`Decimal`, text, integer) from the explicit
   `LegacyThresholdInput` finite-float compatibility alias.
2. Thread a named `financial_input_policy` through threshold parsing,
   `variance_frame`, and `analyze_variance`. Direct Python defaults remain
   legacy-v1 and warn when accepting a finite binary float. Strict-v2 rejects
   binary floats before loading inputs or creating an output directory.
3. Make the CLI select strict-financial-input-v2 explicitly. Extend the AST
   compatibility perimeter so no production `analyze_variance` call can omit
   that selection.
4. Advance the current variance report writer from schema v2 to v3 and its
   nested threshold policy from v1 to v2. Threshold-policy v2 includes
   `financial_input_policy` in the SHA-256 digest.
5. Preserve unversioned/v1 and schema-v2 readers. Unversioned/v1 reports and
   v2 threshold-policy-v1 reports imply legacy-financial-input-v1; they are not
   rewritten or relabeled. The documented schema has separate v2/v3 branches
   that forbid a v3 policy field in v2 and require it in v3.
6. Preserve exact threshold lexemes, comparison semantics, zero-threshold
   behavior, inclusive boundaries, report rounding, result rows, legacy
   numeric threshold keys, and local-only operation.

## Consequences

- New CLI reports carry strict-v2 ingress provenance. New direct-service
  reports carry legacy-v1 provenance unless the caller selects strict-v2.
- Changing only the recorded financial-input policy invalidates the v3 policy
  digest. Unknown policies fail closed without echoing input data.
- Historical v2 policy digests reproduce under the original v1 payload and
  remain schema-valid. Historical artifacts gain no guarantee they did not
  previously record.
- The report/schema change is additive for consumers of the legacy numeric
  `thresholds` keys, but version-aware consumers should accept v3 and inspect
  the nested policy.
- No database migration, network access, telemetry, currency assumption, or
  new financial arithmetic is introduced.

## Rollback

Keep all unversioned/v1, v2, and v3 readers while their artifacts are
supported. Never strip `financial_input_policy` from a v3 report, recompute it
as a v2 digest, or relabel v2 as strict. Reverting the current writer requires
a separately versioned migration and continued v3 verification; restoring an
implicit CLI parser policy is unsafe.
