# ADR 0877: Opt-in guarded amount parser without changing recorded ingress policies

Status: experimental, 2026-10-27.

The existing `strict-financial-input-v2` is persisted in reconciliation jobs and
evidence. Its historical parser accepts malformed grouping by removing commas,
and applies the ambient decimal context when negating accounting parentheses.
For example, `1,2` becomes `12`, and `(123456789.25)` can become `-1.23E+8`
under precision 3. Correcting v2 in place would reinterpret recorded jobs.

`parse_guarded_amount_v3` is a separate opt-in library function. It refuses
malformed three-digit groups, embedded spaces, unspecified underscores and
conflicting signs, preserves exact numeric types independently of display locale,
rejects binary floats via the existing strict parser, and negates accounting
parentheses without context rounding. It accepts only built-in str/int and Decimal (not arbitrary subclasses or
third-party scalar objects), supports explicit Arabic/English locale separators,
and returns a Decimal or raises InvalidAmountError. It does not echo
financial values in errors. It is not a registered FinancialInputPolicy or a
replacement for v2 in persisted jobs, API submissions, matching, reports or UI.

Example for an explicit local preflight (not a persisted policy):

```python
from reconforge.utils.money import parse_guarded_amount_v3

amount = parse_guarded_amount_v3("1.234,56", decimal_separator=",", thousands_separator=".")
# amount is Decimal("1234.56"); callers must preserve the parser version.
```

No historical data, journal, policy label or output is rewritten. Existing v1
and v2 behavior, including the documented unsafe edge cases, remains unchanged
for reproducibility; replay still requires the original engine/version and
context. The optional parser is not a release-wide financial-safety fix.

Before any production path adopts this function, define and migrate a new
persisted policy/version across schema, writers, workers, replay, digests,
idempotency, evidence, readers and reporting; prove cross-engine parity,
permutation/replay, migration/rollback, legitimate locale formats and data-quality
exceptions. Old policy records must not be silently relabeled or replayed using
new semantics. Roll back adoption by reverting the versioned caller change;
existing v1/v2 readers remain available.
