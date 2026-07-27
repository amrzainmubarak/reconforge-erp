# ADR 0030: Versioned fail-closed currency policies

## Status

Accepted — P0 financial-correctness foundation.

## Context

The initial `Money` registry returned an invented two-decimal specification for
any unknown code. It was also a mutable process-global dictionary: conversions
such as `to_minor_units()` re-read the latest policy, so a registry change could
alter the meaning of an already-created value. Neither behavior is acceptable
for reproducible financial decisions.

## Decision

- Load the offline default from a packaged, versioned JSON snapshot.
- Reject unknown or malformed codes; never infer precision.
- Record the registry version/digest and per-currency financial-policy digest.
- Capture the resolved minor units and rounding mode inside each `Money` value.
- Reject arithmetic between equal codes created under different policies.
- Preserve legacy `{amount, currency}` serialization and add an explicit
  canonical serialization carrying policy and provenance.
- Permit only explicit, bounded, atomically validated local-file updates. Do
  not fetch currency policy data at runtime.
- Treat ISO 4217 minor units and ReconForge's rounding mode as separate source
  claims. Entries without a published numeric minor unit are not usable until
  an operator supplies an explicit policy.

## Consequences

Present-but-unknown codes now become data-quality exceptions instead of being
matched under a fabricated two-decimal assumption. Applications using custom
codes must register or install their policy before creating financial values.
Missing CSV currency values retain the documented USD compatibility default for
the current stock/GL interface; removing that default requires a versioned
contract migration.

The in-memory registry is process-scoped. Persisted tenant-specific policy
selection and reconciled integration with the existing master-data tables are
future slices and must not be implied by this ADR.

## Validation

- `tests/test_money_currency.py` covers manifest/digest verification, atomic
  file updates, unknown codes, policy drift, canonical serialization, and
  legacy serialization.
- `tests/test_reconciliation_hardening.py` proves that equal unknown-currency
  rows cannot match and remain accounted for as visible exceptions.
- `tests/test_validation.py` checks pre-run unknown-currency reporting.
- Build verification must confirm the JSON snapshot is present in both wheel
  and source distribution artifacts.
