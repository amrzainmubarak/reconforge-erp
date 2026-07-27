# ADR 0084: Bound review-state JSON ingress without discarding legacy coercion

- Status: Accepted
- Date: 2026-07-26
- Decision owners: Workflow Integrity, Platform Security
- Related: ADR 0059, ADR 0071, ADR 0082, ADR 0083, FI-014, R-018, P0-SEC-009

## Context

`review_state.json` is local workflow input consumed by review CLI commands,
Studio, evidence binders, management reports, period comparison, and the legacy
database bridge. Its reader used unrestricted `read_text` plus `json.loads` and
returned an empty state for malformed JSON. That hid a present data-quality
failure as “no reviews” and supplied no byte, graph, duplicate-key, non-finite,
reparse-point, or file-change control. Historical valid files nevertheless need
their tolerant entry coercion: direct maps and the versioned `entries` envelope
remain readable, non-object entries are ignored, and unknown workflow statuses
fall back to their established defaults.

## Decision

1. Define `review-state-json-ingress-v1`: 16 MiB/file, 500,000 graph nodes,
   depth 32, 100,000 items/collection, and 1,000,000 characters/scalar.
2. Reuse the generated-local stable JSON document reader with this narrower
   named policy. Require a regular non-reparse `.json` file, strict UTF-8,
   duplicate-key and non-finite rejection, and equal SHA-256/size before and
   after parsing.
3. Preserve missing-file-as-empty and the existing normalization of a valid JSON
   object. Do not treat malformed, ambiguous, changed, invalid-encoding, or
   over-budget present input as empty review state.
4. Return code-only `GeneratedArtifactError` failures. Review CLI and Studio
   expose generic path-free wording; a rejected update must not replace the
   existing file. The database bridge wraps rejection before database creation
   or mutation. Other internal consumers fail closed through the same error.
5. Inventory the boundary separately as FI-014. Keep unkeyed hashes, producer
   identity, actor authorization, schema approval, disclosure, malware, and
   supported throughput outside the claim.

## Compatibility and consequences

- Current writer output, historical direct maps, the `entries` envelope, unknown
  entry fields, and tolerant status/certification defaults remain compatible.
- A malformed present file now stops dependent work visibly instead of silently
  erasing review context. This is an intentional financial-integrity tightening.
- The shared helper now accepts a caller-supplied structured policy and profile;
  its default remains `generated-artifact-ingress-v1`, so FI-006/FI-007 behavior
  and runtime monkeypatch tests remain unchanged.
- Stable unkeyed fingerprints prove local byte consistency only. They do not
  authenticate who produced or approved the state.

## Rollback

Revert the policy/profile, centralized reader call, consumer error translation,
inventory entry, and tests. No stored artifact or database migration is needed.
Rollback restores silent malformed-file fallback and unrestricted reads and must
be recorded as a workflow-integrity and hostile-file regression.
