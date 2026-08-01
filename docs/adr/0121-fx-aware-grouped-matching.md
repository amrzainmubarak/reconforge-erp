# ADR 0121: FX-aware grouped matching with deterministic rate policy

- Status: Accepted
- Date: 2026-07-27

## Context

Grouped matching already supports deterministic grouped sum reconciliation for exact records,
but it originally assumed each request was single-currency after ingestion. In real
reconciliation workflows, one side can carry bank/cash/statement lines in a different
currency than the configured target ledger currency. Without an explicit FX contract,
replays can disagree across environments and rates, or worse, silently degrade
to incorrect local-currency assumptions.

## Decision

Introduce explicit foreign-exchange-aware grouped matching at the strategy/application
boundary with deterministic policy:

- Extend matching requests with `target_currency` and `fx_rates`.
- Represent each FX profile as a versionable tuple of mappings with the fields
  `base_currency`, `quote_currency`, `rate`, `source`, `rate_type`, and optional
  canonical `effective_at` date.
- Convert every record amount and fee through deterministic exchange-rate selection
  before grouped sum evaluation.
- For each requested currency pair, select the most recent rate whose effective date
  is empty or not later than the record business date.
- When only reverse rate exists, derive deterministic inversion once.
- Reject any conversion path that lacks a matching valid rate profile.

## Consequences

E-110 closes P1-REC-006 with explicit FX governance in grouped matching and a
reproducible conversion step before matching evaluation. FX rate metadata and
selection behavior are now part of matching explainability evidence, and conversion
deficiencies fail closed as explicit exceptions rather than producing unstable outcomes.

## Reversibility

The change is versioned through matching-manifest request fields and can be
replaced later by richer FX engines by introducing a new request field/version
set while keeping existing `MatchingStrategyRequest` defaults for compatibility.
