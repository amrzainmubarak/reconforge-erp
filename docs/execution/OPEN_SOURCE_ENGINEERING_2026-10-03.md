# Open-source engineering references and workload adoption

Date: 2026-10-03. The user confirmed that the target covers individuals through
banks and large institutions, and that no company pilot is currently available.
Public source research and reproducible synthetic workloads advance engineering
acceptance; company hours saved and independent reviewer acceptance remain unmeasured.

The accompanying [source inventory](OPEN_SOURCE_REFERENCES_2026-10-03.json) records
exact upstream commits, license paths and content hashes obtained from the official
repositories. The initial research executed no upstream code. The subsequent
[AMLSim acceptance slice](../validation/amlsim-workload.md) adopts the unmodified
45-row synthetic CSV with its Apache-2.0 license/attribution and runs ReconForge's
offline adapter/oracle. No upstream generator code or dependency stack is executed.
ReconForge's own source remains MIT licensed.

| Official project | Intended concrete use | Adoption boundary |
| --- | --- | --- |
| [TigerBeetle](https://github.com/tigerbeetle/tigerbeetle) | Immutable posting, correcting entries, unique transfer identity, pending/posted effects and retry invariants | Apache-2.0 repository; architectural/test reference. Retain PostgreSQL as the requested production store; do not introduce a second ledger database without measured justification. |
| [LDBC FinBench DataGen](https://github.com/ldbc/ldbc_finbench_datagen) | Temporal/skewed synthetic financial flow input for import, lineage, graph and candidate-pressure workloads | Apache-2.0; upstream identifies v0.1.0 as stable and main as v0.2 work in progress. Pin stable source. A projected reconciliation workload is not an official FinBench result. |
| [IBM AMLSim](https://github.com/IBM/AMLSim) | Pinned 45-row synthetic sample now used by the offline reconciliation fault oracle | Apache-2.0 fixture plus attribution retained; upstream generator from 2022 and its legacy Python/Java stack are not executed. Seeded faults are ReconForge additions. No AML/fraud efficacy claim. |
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

PROD-022 now has one bounded executable adoption: 45 upstream sample records,
42 exact matched pairs and three unmatched records per side after four seeded
faults, with independent decision checks and row-permutation replay. The source
inventory JSON remains the historical initial research observation; new execution
evidence records the later dataset import. FinBench execution, larger workloads,
PostgreSQL worker acceptance and external customer outcomes remain unmeasured.
