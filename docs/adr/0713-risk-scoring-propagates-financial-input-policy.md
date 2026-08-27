# ADR 0713: Risk Scoring Propagates Financial Input Policy

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: Risk scoring converted amount inputs through the default parser
  without receiving the reconciliation run's selected financial-input policy.
  This left a compatibility path where binary floating-point input could be
  accepted by a risk calculation even when the surrounding run was strict.
- **Decision**: Make the financial-input policy an explicit keyword on risk
  scoring and amount-component APIs. Propagate the selected policy from Stock
  and Work-order reconciliation and from WIP aging; strict v2 remains the
  default for new callers, while legacy v1 remains available only when named.
- **Verification**: Risk tests prove a binary float is accepted only under the
  explicitly named legacy policy and is treated as invalid under strict v2.
  Existing reconciliation/report tests preserve current exact inputs.
- **Compatibility**: Exact Decimal, integer, and text inputs keep their prior
  scores. No stored amount is changed; invalid risk inputs remain a neutral
  score input and are not converted into a financial amount.
- **Rollback**: Revert E-1053 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore an implicit parser policy.
