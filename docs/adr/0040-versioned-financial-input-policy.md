# ADR 0040: Version Financial Input Policies

- Status: Accepted
- Date: 2026-07-25
- Scope: Canonical amount parsing and the first strict-reader migration group

> Current-path note: ADR 0057 supersedes decision item 4 only for application
> configuration loading. CLI, benchmark, and Studio now select strict-v2 after
> preserving YAML decimal lexemes as text. Direct `ReconForgeConfig` and
> `load_config` defaults remain legacy-v1 compatibility readers.

## Context

Several public library boundaries historically accepted Python or NumPy binary
floating-point values and immediately converted their shortest text form to
`Decimal`. This preserved common calls such as `0.1`, but the original source
lexeme was already lost before ReconForge received it. Removing that behavior
in place would break existing Python callers and PyYAML configurations, while
leaving it implicit would make it impossible to prove which ingestion paths are
exact.

The reconciliation-signature v2 boundary already rejects these values. The same
rule needs one reusable parser policy before internal readers can migrate in
small, testable groups.

## Decision

Define two named input policies:

- `legacy-financial-input-v1` retains finite binary floating-point compatibility,
  converts via the historical shortest text representation, and emits
`LegacyFinancialInputWarning` from public parsing helpers after the value has
proved finite. The warning registry is lock-protected and emits once per source
call site even when a test or host selects an `always` warning filter.
- `strict-financial-input-v2` rejects Python and NumPy floating scalars before
  text conversion. It accepts finite `Decimal`, integer, and exact plain-decimal
  text subject to the existing separator, scientific-notation, and currency-
  precision rules.

`CURRENT_FINANCIAL_INPUT_POLICY` is strict v2. Existing `parse_amount` and
`parse_amount_for_currency_precision` defaults remain legacy v1 for source
compatibility; new internal work must call `parse_exact_amount` or
`parse_exact_amount_for_currency_precision`. The default can change only at a
documented breaking-release boundary.

Migrate the first bounded group now:

1. CSV/XLSX dataset coercion uses strict v2. File readers already load cells as
   text; a programmatically supplied floating scalar becomes a visible invalid
   value with its raw compatibility text instead of a valid amount.
2. Reconciliation tolerance comparisons use strict v2 because Pydantic has
   already stored the configured tolerance as `Decimal`.
3. Signature-v2 financial text parsing uses strict v2 in addition to its
   field-level type assertion.
4. `ReconForgeConfig` explicitly names legacy v1 because safe PyYAML may produce
   a floating scalar for an existing unquoted `2.0`; accepted uses warn.

Internal `Money` construction suppresses repeated parser warnings because the
matching candidate loop can instantiate the same legacy value many times. This
does not make the input strict or approved: the outer legacy boundary remains
classified and will be migrated separately. Error messages name the policy and
type class but never echo the financial value.

## Consequences

- Strict parsing behavior is reusable and independently testable for Python and
  NumPy scalar types, hostile Decimal contexts, currency precision, malformed
  policies, and non-finite values.
- The official file path stays byte/lexeme preserving because CSV/XLSX cells are
  strings. Direct callers of the internal coercion helper that supplied a
  floating scalar now receive a data-quality value rather than silent acceptance.
- Legacy callers continue to work for finite values and receive a deprecation
  warning at public parser/config boundaries.
- Canonical `Money` identity does not include the ingress policy: once two exact
  values are accepted under an approved path, equal amount/currency/policy values
  remain equal. Import/run evidence must record ingress policy separately in a
  future manifest slice.
- The lexical `float` audit increases by one intentional strict rejection guard;
  this is a safety control, not a regression.

## Rollback

Callers may explicitly select legacy v1 while migrating, but strict readers must
not silently fall back after rejection. Reverting a migrated internal reader
requires a compatibility test, a recorded reason, and updated evidence. Removing
v1 or changing the default requires a versioned breaking change and release note.
