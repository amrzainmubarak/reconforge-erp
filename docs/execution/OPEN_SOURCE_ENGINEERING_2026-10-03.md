# Open-source engineering references and workload adoption

Date: 2026-10-03. The user confirmed that the target covers individuals through
banks and large institutions, and that no company pilot is currently available.
Public source research and reproducible synthetic workloads advance engineering
acceptance; company hours saved and independent reviewer acceptance remain unmeasured.

The accompanying [source inventory](OPEN_SOURCE_REFERENCES_2026-10-03.json) records
exact upstream commits, license paths and content hashes obtained from the official
repositories. No third-party source has been copied into the runtime or executed
by this research slice. Preserve ReconForge's MIT license and attributable notices
if a later slice imports permitted code or data.

| Official project | Intended concrete use | Adoption boundary |
| --- | --- | --- |
| [TigerBeetle](https://github.com/tigerbeetle/tigerbeetle) | Immutable posting, correcting entries, unique transfer identity, pending/posted effects and retry invariants | Apache-2.0 repository; architectural/test reference. Retain PostgreSQL as the requested production store; do not introduce a second ledger database without measured justification. |
| [LDBC FinBench DataGen](https://github.com/ldbc/ldbc_finbench_datagen) | Temporal/skewed synthetic financial flow input for import, lineage, graph and candidate-pressure workloads | Apache-2.0; upstream identifies v0.1.0 as stable and main as v0.2 work in progress. Pin stable source. A projected reconciliation workload is not an official FinBench result. |
| [IBM AMLSim](https://github.com/IBM/AMLSim) | Transaction schema and synthetic flow-pattern reference, including dense accounts and repeated counterparties | Apache-2.0; current pinned commit is from 2022 and README requires legacy Python/Java packages. Do not import its old dependency stack into production. Synthetic labels do not establish AML/fraud detection efficacy. |
| [Apache Fineract](https://github.com/apache/fineract) | Banking operation lifecycle, accounting boundary and command retry reference | Official README states Apache-2.0, while GitHub identifies the composite LICENSE_RELEASE as NOASSERTION. Retain that distinction; inspect exact component/NOTICE terms before any code adoption. |
| [React Aria / React Spectrum](https://github.com/adobe/react-spectrum) | Keyboard interaction, focus recovery, accessible forms and Arabic RTL reference for financial writes | Apache-2.0; evaluate individual components against current React, bundle size and existing CSP before adding dependencies. Public accessibility support is not evidence that ReconForge itself passes manual accessibility review. |

[ERPNext's immutable ledger](https://docs.frappe.io/erpnext/immutable-ledger-in-erpnext)
and [stock accounting](https://docs.frappe.io/erpnext/accounting-of-inventory-stock)
remain useful behavior references. Its [published license](https://erpnext.com/license-trademark)
is GPLv3 for code and CC-BY-SA for documentation; this plan does not copy that
implementation into the MIT runtime or change ReconForge's license.

## Executable acceptance sequence

1. Close known money/currency, authorization and transactional integrity defects
   before using throughput numbers to justify the platform.
2. Add an opt-in source adapter that reads locally supplied synthetic transaction
   files. Validate schema, currency policy, exact decimal lexemes, stable source
   identity and timestamps. Preserve source commit, input checksum and mapping
   version in its manifest. Default runtime operation remains offline.
3. Derive two reconciliation sides using a versioned, explicitly documented
   projection. Seed missing, duplicated, delayed and amount-changed records with
   a separate expected-outcome oracle. Keep upstream generator labels distinct
   from these ReconForge reconciliation labels.
4. Execute 10K then 100K, then 1M and a 5M/30-definition workload only after
   preceding correctness/resource gates pass. Record input counts, discrepancies,
   ambiguity, output digests, memory, CPU, elapsed time and crash/resume behavior.
   A generation count alone is not a processed transaction count.
5. Test posting against exact per-currency debit/credit conservation, immutable
   reversal, one source effect on retries and atomic stock/subledger/GL effects.
   Use the same assertions for SQLite and PostgreSQL without copying an upstream
   implementation as the test oracle.
6. Deliver the connected financial journeys with permission-aware forms, exact
   amounts, conflict recovery, source evidence and Arabic/English keyboard flows.
   Preserve the small local installation while expanding optional sector packs.

The immediate source integration work is PROD-022. Current evidence establishes
source provenance and an adoption contract only; no external generator, imported
dataset, comparative throughput result or customer outcome has been claimed.
