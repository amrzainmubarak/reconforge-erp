# Deterministic Consolidation Translation Foundation

ReconForge provides an Experimental library and immutable-artifact foundation
for translating multiple balanced entity trial balances into one reporting
currency. It is a calculation and evidence boundary, not a complete financial
consolidation system.

## What the v1 contract proves

For one explicit request, the engine proves that:

1. at least two source entities are present;
2. each entity has one functional currency and one source trial-balance digest;
3. every entity's signed source balances net exactly to zero before translation;
4. every foreign-currency line resolves to one and only one explicit period,
   currency-pair, rate-type, and rate-bucket record;
5. currency precision and rounding come from the installed versioned registry;
6. input order cannot change the request ID, translated lines, account totals,
   adjustment proposal, or result digest; and
7. a stored artifact can be replayed from its declared inputs and rejected when
   financial content is changed, even if a new outer hash is supplied.

The three rate-type labels are closed identifiers: `closing`, `average`, and
`historical`. Each line also selects an explicit rate bucket, allowing different
historical layers within one currency. The caller chooses both fields; the engine
does not infer a legal accounting policy.

## Financial output

Each translated line retains:

- source line and source trial-balance SHA-256;
- entity, source account, mapped group account, and account type;
- original canonical Money value and currency-policy lineage;
- selected rate ID, type, exact value, source, source SHA-256, and effective time;
- unrounded translated value;
- reporting-currency Money value after registry rounding; and
- the exact rounding delta.

The result aggregates by mapped group account and exposes:

- the unrounded translation difference caused by applying different rate types;
- the total rounding delta;
- the reporting-currency balance before adjustment;
- an explicit translation-adjustment proposal; and
- the mathematical balance after applying that proposal.

The proposal has `posted=false`. No journal, elimination, approval, period close,
ERP mutation, or bank action is created.

## Storage and replay boundary

`ObjectStoreConsolidationResultRepository` stores canonical schema-v1 JSON through
the existing immutable object-store contract. The object key is separated by
tenant and workspace. An identical retry returns the existing object only after
its bytes match; a conflicting object fails closed. Reads verify object integrity,
parse under bounded JSON limits, reconstruct the calculation, and compare the
complete canonical result.

The closed artifact schema is
`docs/schemas/consolidation-translation-result-v1.schema.json`. The architecture
decision is ADR 0210.

## Current limits and next gates

This foundation does not yet implement:

- ownership hierarchies, effective ownership dates, or non-controlling interests;
- investment/equity, intercompany balance, unrealized-profit, dividend, or cash-
  flow eliminations;
- acquisition, disposal, step acquisition, or hyperinflation accounting;
- remeasurement into functional currency;
- consolidation journals, maker-checker approval, period locking, or reversal;
- persisted database run lifecycle, distributed scheduling, or a Studio workflow;
- statutory balance sheet, income statement, cash-flow statement, notes, or XBRL;
- live exchange-rate providers, source ERP posting, or write-back; or
- IFRS, US GAAP, local-GAAP, audit, compliance, certification, or legal assurance.

Those limits keep the allowed wording narrow: “deterministic multi-entity
translation artifact foundation.” Do not call it full consolidation, statutory
reporting, Enterprise-ready, compliant, certified, or the best globally.
