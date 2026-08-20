# ADR 0413: Expose bounded sequential matching through Reconciliation-as-Code

- **Status:** Accepted
- **Date:** 2026-08-07
- **Scope:** Reconciliation-as-Code matching simulation

## Context

The experimental `bounded-carry-forward-fifo` and `bounded-reversal-pairing`
adapters already execute through the PostgreSQL sequential worker boundary, but
RAC v1 could not declare or exercise them. This split made a versioned rule pack
less expressive than the tested worker surface and encouraged ad-hoc rule JSON.

## Decision

Add `carry_forward`, `sequence_window`, and `reversal_pairing` strategy types to
RAC v1. Resolve them only to the existing bounded strategy identities, dispatch
through the same digest-verified `MatchingStrategyResult` envelope, and report
allocation/pair and residual counts in embedded synthetic tests. Keep the
strategies experimental, read-only, and human-governed; no journal posting,
write-back, provider call, or autonomous approval is introduced.

## Safety and compatibility

- Existing one-to-one, grouped, and duplicate modes retain their defaults.
- The JSON Schema remains closed and rejects an incompatible sequential adapter.
- Exact Decimal text, date windows, partition identity, candidate/search ceilings,
  deterministic ordering, and unresolved ambiguity remain enforced by the
  existing strategy implementations.
- The change is additive and reversible by removing the RAC dispatch branches;
  no database migration is required.

## Evidence boundary

Focused RAC, schema, carry-forward, reversal, and phase-2 contracts pass. This
proves declaration and local simulation only; it does not prove statutory
settlement, production matching capacity, cross-engine parity, provider
interoperability, or write-back.
