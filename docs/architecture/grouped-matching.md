# Bounded grouped matching

`bounded-grouped-subset-sum@1.0.0` is the first true grouped financial-match
strategy. It is experimental and separate from the legacy `match run`
pair-capacity flags. Those flags preserve compatibility and must not be
described as sum-constrained grouped matching.

The strategy supports one-to-many, many-to-one, and many-to-many groups. Every
candidate group must use one currency and one explicit partition key, remain
inside the configured date window and cardinality ceilings, and satisfy the
exact-Decimal sum tolerance. Binary floating-point and non-finite amounts are
rejected at the application boundary.

## Search and selection

Records are sorted by stable business identity before search. For left
cardinality ceiling `L`, right ceiling `R`, and input sizes `n` and `m`, the
worst-case enumeration is bounded by:

`sum(C(n, i), i in allowed-left) * sum(C(m, j), j in allowed-right)`

The published runtime ceilings are four records on either side and 25,000
evaluated group pairs. A caller may request a lower reviewed budget for a
single run (`max_left_cardinality`, `max_right_cardinality`, or
`max_search_evaluations`), but never a value above the manifest ceiling or
below the selected mode's cardinality floor. The selected override is part of
the canonical request digest. Crossing the effective evaluation ceiling produces
`GROUP_SEARCH_BUDGET_EXCEEDED`, selects no group, and records the partial
candidate count. This is a deterministic search budget, not a performance
claim.

Candidates are ranked by absolute sum difference, total cardinality, date
span, then stable record identities. The decision records the rule, sums,
currency, candidates and evaluations, explanation, group ID, and SHA-256
decision digest. Equal business-cost candidates use the published stable
identity tie-break.

## Deliberate limits

- The v1 operation selects one group per request; batch non-overlap assignment
  is not implied.
- Fees and FX conversions are modeled via versioned grouped-request policy (`netting`
  and `target_currency` + `fx_rates`). Carry-forward, partial settlement, and
  throughput claims remain out-of-scope for this slice.
- Throughput is not supported until reproducible grouped benchmarks exist.
- The strategy has no persistence side effects and works without network
  access or a database.
