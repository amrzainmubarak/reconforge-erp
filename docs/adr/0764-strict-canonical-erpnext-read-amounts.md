# ADR 0764: Strict canonical ERPNext read amounts

- **Status**: Accepted
- **Date**: 2026-08-28
- **Context**: ERPNext GL Entry and Payment Entry read models used local
  `Decimal(value)` validation and returned source text unchanged. Scientific
  notation could therefore cross the provider response boundary, and
  equivalent values could produce different response fingerprints.
- **Decision**: Route ERPNext read-only debit, credit, paid, and received
  amounts through `canonical_connector_amount()`. Use the strict parser for
  the model's derived arithmetic and preserve the existing non-negative,
  one-sided, and non-zero business invariants.
- **Rationale**: Provider response data must be exact and canonical before
  company scoping, replay digest construction, or derived financial checks.
  Read-only ERPNext input must share the same connector policy as the generic
  reference sources without widening the provider or write-back contract.
- **Compatibility**: Field aliases, response shape, cursors, company scope,
  token transport, and error categories remain unchanged. Exact finite values
  remain accepted but are returned as canonical plain text; negative GL/Payment
  amounts remain invalid under the existing domain boundary.
- **Verification**: ERPNext GL and Payment Entry read tests cover canonical
  output, scientific/non-finite/negative refusal, one-sided and non-zero
  invariants, company scoping, cursor/query behavior, token isolation, SDK
  inventory, and TLS/retry contracts. Full regression and release gates are
  recorded in E-1104.
- **Rollback**: Revert E-1104, ADR 0764, ERPNext read connector/test changes,
  manifest entry, and execution records together. Write-back contracts remain
  independently governed.
