# ADR 0528: Core matching and Stock/GL result policy metadata fails closed

- **Date**: 2026-08-11
- **Status**: Accepted

## Context

E-717 made Work-order result construction validate its financial-input policy.
The same metadata is carried by the Stock/GL result and the backend-neutral
matching result types. Their execution paths already validate policy values,
but a direct caller could still construct an unsupported runtime string and
pass it to a downstream consumer.

## Decision

Validate and normalize `financial_input_policy` in the frozen
`StockGLReconciliationResult`, `MatchRunResult`, and
`DeterministicMatchOutput` constructors. Unsupported values raise the existing
`InvalidAmountError` before a result can escape. Explicit legacy-v1 remains
representable for named historical compatibility, while strict-v2 remains the
default.

## Verification

The Stock/GL and application-matching tests reject unsupported construction;
the combined exactness/report/matching suite passes 33 tests, and the current
full local regression collects 2,935 tests and passes 100% with only declared
capability skips and existing warnings. Ruff and Mypy pass. No schema,
migration, artifact, provider, posting, write-back, or publication behavior
changes.

## Rollback

Revert the three validators, regression tests, ADR, manifest, and E-718 records
together. Existing strict-v2 and explicit legacy-v1 semantics remain unchanged.
