# ADR 0045: Versioned Golden Finance Dataset Registry

- Status: Accepted
- Date: 2026-07-25
- Scope: Synthetic stock/GL input bytes and deterministic expected outputs

## Context

The synthetic generator already emitted a strong generation manifest, but it
did not freeze expected reconciliation results. The sample-data documentation
listed qualitative signals while explicitly allowing exact counts to drift.
That is useful demonstration material but cannot detect an unexplained change
to decisions, policies, summary order, or signature v3. P0-010 requires
versioned datasets, schemas, SHA-256 manifests, expected outputs, and an update
policy.

## Decision

1. Add closed JSON Schema v1 and
   `tests/golden/finance_registry.v1.json` as the synthetic-only registry.
2. Freeze two bounded stock/GL cases:
   - the existing workshop sample under its exact CSV bytes; and
   - a focused exact/duplicate/malformed-date-and-amount/JPY/cross-currency
     boundary case.
3. Record each input path, byte count, SHA-256, exact Decimal configuration,
   expected counts, domain-ordered summary, signature v3, strict financial
   input policy, and canonical record-identity policy.
4. Chain integrity at four levels: file digest, expected-output digest, case
   digest, and registry digest. Canonical JSON uses sorted keys, compact
   separators, and ASCII escaping for digest calculation.
5. Validate repository-contained paths and exact bytes, then run every case
   through Pandas, DuckDB full scan, and forced DuckDB partition execution.
   Missing DuckDB remains an explicit skip and is not parity evidence.
6. Govern changes through `docs/testing/golden-finance-datasets.md`: synthetic
   data only; version instead of silently overwriting a frozen case; explain
   signature/policy changes through an ADR; and review inputs independently
   from expected-output changes.
7. Include registry, schema, policy, and input bytes in the source distribution
   through `MANIFEST.in`. Keep them out of the runtime wheel because they are
   development/release evidence rather than product runtime data.

## Consequences

- An unexplained input-byte, expected-output, policy, digest, or summary-order
  change now fails a small deterministic gate.
- P0-010 is complete for the bounded stock/GL golden-registry exit evidence.
- The cases are diagnostic, not statistically representative or performance
  datasets. They do not prove every currency, strategy, accounting use case,
  supported dependency version, or live backend.
- P0-009 gains golden multi-currency/quality evidence but still requires the
  declared Python/Pandas/DuckDB version matrix and denser ambiguity cases.

## Rollback

Do not delete or rewrite a published registry version merely because behavior
changes. Retain the failing version as compatibility evidence and add a new
version after the governing migration/ADR. Removing a case is acceptable only
for a documented safety, legal, or data-provenance reason; no real or customer
data may replace it.
