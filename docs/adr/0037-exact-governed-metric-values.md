# ADR 0037: Exact Governed Metric Values

- Status: Accepted
- Date: 2026-07-24
- Scope: local DB-backed governed metric snapshots

## Context

Close completion, evidence coverage, control effectiveness, match rate, and
period readiness were calculated or normalized through binary float. The
service then derived `metric_snapshots.value_text` from that float, even though
the schema already provided the text field needed for a stable exact
representation. Non-finite stored readiness could also be converted into a
dashboard path without an explicit data-quality failure.

These metrics do not authorize the underlying financial workflow, but they are
displayed to reviewers and can influence operational attention. Their lineage
must distinguish an exact count-derived metric from the legacy numeric display
projection.

## Decision

1. Compute count percentages from integer numerator/denominator values with a
   derived local Decimal context, `ROUND_HALF_UP`, and quantum `0.01`.
2. Make the existing `value_text` field the canonical metric representation.
   Store fixed decimal text for percentages/ages and integer text for counts.
3. Continue writing the same text to the legacy `value REAL` column so existing
   API/Studio numeric readers remain compatible. SQLite may project this column
   as a binary numeric value; it is not the authoritative representation.
4. Average period-readiness text values with exact Decimal arithmetic and reject
   non-finite or out-of-range stored readiness rather than substituting zero.
5. Cast SQLite `AVG(julianday(...))` aging output to text, validate finiteness,
   and quantize it under a local context. This removes an application float
   conversion but does not make SQLite's underlying time aggregate exact.
6. Preserve the existing empty-set policies: evidence coverage is `100.00`
   without requirements; other percentage/count/aging metrics are zero.

## Consequences

- `value_text` is stable under hostile ambient Decimal precision and carries
  `33.33` rather than a float-derived string.
- Existing `value`, API routes, metric keys, lineage records, and Studio pages
  remain. Consumers needing deterministic values should prefer `value_text`.
- Some text formatting becomes more explicit: zero percentages use `0.00`,
  while count metrics use `0`.
- The local schema still contains a REAL compatibility column. Replacing it
  requires a versioned migration and compatibility reader.
- Stored readiness is still snapshot state and may become stale if callers
  bypass the close service. This slice validates representation; it does not add
  scheduling or automatic recomputation.

## Security and governance

Invalid stored metric state fails with a bounded non-reflecting application
error before snapshot writes/audit commit. Metrics remain local and contain no
new raw financial rows, network calls, or telemetry. They do not provide an
audit opinion, executive assurance, certification, or statutory close.

## Rollback

Legacy readers can continue using `value`. Restoring float-derived
`value_text` is unsafe because it removes the canonical representation. A
future migration may add a text-only/versioned metric value while retaining a
compatibility numeric projection.
