# ADR 0753: Strategy adapters enforce strict financial inputs

- Status: Accepted
- Date: 2026-08-28
- Decision owners: ReconForge execution stream

## Context

The domain models for carry-forward allocation and reversal pairing require
exact `Decimal` amounts. Their public strategy adapters, however, converted
record amounts with `Decimal(str(value))`. That conversion can turn a Python
binary `float` into an apparently valid decimal string before the domain
boundary sees it. The same compatibility leak existed for the carry-forward
amount tolerance. This made the adapter contract weaker than the strict
financial-input policy used by the rest of the matching surface.

## Decision

The carry-forward and reversal-pairing adapters must parse every amount and
tolerance through `parse_exact_amount()`. Binary floating-point values are
rejected at the adapter boundary; exact text, integers, and `Decimal` values
remain supported. The adapter exposes the safe parser reason through the
existing `MatchingStrategyContractError` without including the input value.

## Consequences

- Sequential matching strategies cannot silently reinterpret binary floating
  point as exact financial data.
- Both adapters now share the strict parser used by grouped matching and FX
  conversion.
- This is input-type and adapter-boundary evidence; it does not establish
  posting correctness, provider authenticity, cross-engine parity, or
  production financial assurance.
- Existing exact-text strategy requests retain their result and digest
  behavior.

## Verification

- `tests/test_matching_strategy_contract.py::test_sequential_strategy_adapters_reject_binary_float_amounts`
- Existing carry-forward, reversal, sequential-worker, matching replay, and
  strategy-contract tests
- Full regression and release gates recorded in `docs/execution/EVIDENCE.md`

