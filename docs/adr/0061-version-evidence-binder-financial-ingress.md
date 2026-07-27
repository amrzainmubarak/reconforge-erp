# ADR 0061: Version Evidence-Binder Financial Ingress and Index

- Status: Accepted
- Date: 2026-07-25
- Scope: local evidence-binder CSV/risk ingress, current index integrity, and historical compatibility

## Context

Evidence risk scores control which exception rows enter a review binder and how
they are classified. The score parser used exact `Decimal` validation, but
`pandas.read_csv` could first infer a column as binary floating point. A source
lexeme such as `60.000000000000000001` could therefore collapse to `60.0` and
be excluded instead of remaining a visible invalid-score data-quality case.

Historical `evidence_index.json` schema v2 records the bounded integer
score policy and explicit valid/missing/invalid status, but it does not record
the financial-input policy, selected source bytes, tool version, or document
digests. Historical direct Python behavior remains a compatibility surface.

## Decision

1. Thread an explicit financial-input policy through recognized exception,
   matched-transaction, and rule-result CSV reads plus risk parsing and case
   collection. Direct Python entry points default to
   `legacy-financial-input-v1`; current CLI/demo paths explicitly select
   `strict-financial-input-v2`.
2. Under strict v2, read all CSV fields as text with empty strings preserved.
   Validate risk scores from the original lexeme under the existing
   `integer-0-to-100-v1` rule. Fractional, malformed, non-finite, scientific,
   overlong, or out-of-range explicit scores remain invalid and visible as
   data-quality evidence; missing values remain distinct.
3. Preserve the exact historical schema-v2 index shape for explicit legacy
   generation and label it `legacy-unverified` in the compatibility reader.
   Current strict generation advances to schema v3.
4. Schema v3 records artifact/tool identity, strict input policy, risk-score
   policy, sorted relative SHA-256/byte fingerprints for all recognized input
   files, case count/cases, and an explicit integrity boundary. Recognized
   files include the four exception reports, two matched-transaction reports,
   two rule-result locations, and review state when present.
5. Fingerprint the selected source set before case generation, recompute the
   complete recognized set before writing the index, and fail if any selected
   source was added, removed, or changed during generation.
6. Add a path-independent `content_digest` over policy, input fingerprints,
   case decisions, and provenance while excluding per-case generation times.
   Add an `artifact_digest` over the complete index including timestamps.
7. Provide a current verifier that validates policy, cases, paths, counts,
   fingerprints, and both digests. An optional local source directory rehashes
   the complete recognized input set. The existing evidence manifest remains
   the checksum inventory for generated output bytes.
8. Treat all hashes as local consistency evidence only. They do not
   authenticate the source system or actor, provide a signature, prove evidence
   completeness, approve a review decision, or constitute an audit opinion.

## Consequences

- Strict `60.000000000000000001` stays fractional and becomes a visible
  data-quality case; legacy pandas inference may collapse it to valid `60` and
  exclude it. The compatibility behavior is preserved but explicitly named.
- Current CLI/demo output changes from index schema v2 to v3. Consumers that
  only inspect `case_count` and `cases` continue to find those fields; consumers
  enforcing an exact top-level shape must adopt the v2/v3 schema or reader.
- A newly visible invalid row can shift generated sequential case IDs. This is
  an intentional correction at the file-report boundary, not a stable source
  identity claim; durable evidence-graph IDs remain separate roadmap work.
- Equivalent recognized inputs in different local folders reproduce the same
  content digest. Artifact digests may differ because generation timestamps are
  deliberately covered.
- Source fingerprints cover only the documented local report inputs. They do
  not attest upstream exports, and the binder remains file-based rather than a
  durable evidence graph or signed/WORM store.

## Rollback

Retain the schema-v2 writer/reader and explicit legacy policy throughout the
compatibility window. Do not route current CLI/demo generation through an
implicit default, restore pandas inference on the strict path, discard invalid
scores, relabel v2 as strict/verified, or describe local hashes as signatures.
Any future writer must version its schema and preserve v2/v3 reading with a
documented migration and rollback path.
