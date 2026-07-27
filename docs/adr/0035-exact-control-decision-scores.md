# ADR 0035: Exact Control-Decision Scores

- Status: Accepted
- Date: 2026-07-24
- Scope: evidence-binder risk scores and local/PostgreSQL close readiness

## Context

Evidence-binder selection used Pandas numeric coercion and then converted a
selected score through `float` and `int`. Malformed values could be treated as
zero during selection or could abort generation, while fractional values were
silently truncated. PostgreSQL close approval/locking converted the computed
readiness value to binary float before comparing it with 100. Local and
PostgreSQL readiness calculations also derived percentages through float
division.

These values are not financial amounts, but they affect which exceptions become
review evidence and whether a close-control workflow may be approved or locked.
Their decision semantics therefore require the same determinism and explicit
invalid-data treatment as other control boundaries.

## Decision

1. Define evidence-binder risk score policy `integer-0-to-100-v1`. Parse a
   bounded, finite, plain-decimal value and accept it only when it is an exact
   integer from 0 through 100. Scientific, fractional, malformed, overlong, and
   out-of-range values are invalid.
2. Keep malformed explicit scores visible as evidence data-quality cases. Emit
   `risk_score: null`, `risk_score_status: invalid`, and severity
   `Data Quality`; never publish a manufactured numeric zero. Missing scores
   remain distinguishable from invalid scores and are still selected when the
   declared level is High/Critical.
3. Version `evidence_index.json` as schema 2 and add the score policy/status.
   HTML, Markdown, and the spreadsheet register show invalid/missing scores as
   unavailable while valid score output remains unchanged.
4. Compute readiness from integer task counts with a derived local Decimal
   context, `ROUND_HALF_UP`, and a fixed percentage quantum of `0.01`.
5. Require exact equality with `Decimal("100.00")` for PostgreSQL close
   approval/locking. Do not parse or round an externally supplied score at that
   decision point; an unexpected representation fails closed.

## Consequences

- Valid integer risk scores and existing evidence filenames remain compatible.
  Schema-2 fields are additive for valid cases.
- An explicitly malformed score that was previously omitted or represented as
  zero now produces a visible data-quality case with a null score. Consumers
  that require an integer must inspect `risk_score_status` or remain on a
  schema-1 compatibility reader.
- Readiness values retain the existing two-decimal presentation, but their
  calculation and the completion decision no longer depend on binary float or
  ambient Decimal precision.
- The local SQLite column retains its existing `REAL` schema for migration
  compatibility. Current decisions derive from exact integer counts rather
  than re-reading that storage value; changing storage affinity requires a
  separate versioned migration.

## Security and governance

Malformed score text is not reflected in a generated error message. The source
record already present in the local evidence case remains available to an
authorized reviewer. A ReconForge close-control lock remains workflow metadata
only and does not lock source-ERP postings or constitute a statutory close,
approval opinion, or certification.

## Rollback

Schema-2 readers can ignore additive policy/status fields for valid historical
cases. Restoring silent invalid-to-zero coercion, float truncation, or float
completion comparison is unsafe. A rollback may preserve schema-1 historical
artifacts, but newly generated malformed-score evidence must retain explicit
quality status.
