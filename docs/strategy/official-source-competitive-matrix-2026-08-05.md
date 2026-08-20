# Official-Source Competitive Matrix (2026-08-05)

This is an ethical, evidence-bounded comparison. It records capabilities that
the cited first-party documentation describes; it does not rank products or
claim that ReconForge is better. A source page is not treated as proof of a
vendor's performance, security assurance, implementation quality, or customer
outcomes.

## Reading rules

- Only first-party documentation is used for a competitor observation.
- ReconForge observations point to code, tests, or execution evidence already
  present in this repository.
- A blank or unresolved ReconForge cell is a gap, not an invitation to infer a
  capability from a similarly named API.
- No pricing, throughput, regulatory, or production claim is inferred when the
  source does not publish comparable evidence.

## First-party sources

| Source | Official documentation used | Narrow observation recorded here |
| --- | --- | --- |
| Odoo | [Bank reconciliation](https://www.odoo.com/documentation/19.0/applications/finance/accounting/bank/reconciliation.html); [bank synchronization](https://www.odoo.com/documentation/18.0/applications/finance/accounting/bank/bank_synchronization.html) | Reconciliation models/rules, partial and netting flows, and bank synchronization through third-party providers are documented. |
| ERPNext | [Accounting introduction](https://docs.frappe.io/erpnext/accounting/introduction); [banking](https://docs.frappe.io/erpnext/bank) | Double-entry, multi-company and multi-currency accounting plus bank-statement upload/reconciliation are documented. |
| Apache Fineract | [Current project documentation](https://fineract.apache.org/docs/current/) | Fine-grained maker-checker controls for state-changing APIs and an accounting area are documented. |

## Like-for-like capability map

| Dimension | What the official sources document | ReconForge evidence in this workspace | Honest gap / safe interpretation |
| --- | --- | --- | --- |
| Reconciliation workflow | Odoo documents reconciliation models, suggestions, partial reconciliation and netting. ERPNext documents bank-statement upload and reconciliation mapping. | CAMT.053 is parsed locally and projected into bounded statement pages (`reconforge/connectors/camt053.py`, E-388). Grouped, FX-aware, fee-aware and partial-settlement decisions are versioned and explainable (E-392 and the grouped strategy contracts). | No live provider feed is evidenced. These are adjacent workflow observations, not feature parity or usability equivalence. |
| Accounting breadth | ERPNext documents double-entry, multi-company and multi-currency accounting integrated with other ERP areas. Odoo documents accounting and bank workflows inside its ERP. | ReconForge has bounded consolidation, close-management and non-posting evidence contracts; its declared position remains an audit/control layer beside source systems. | Statutory books, universal ERP transaction processing and full consolidation remain outside the verified scope. |
| Maker-checker and policy controls | Fineract documents maker-checker for state-changing API operations; the ERP sources document role-controlled accounting workflows at their product boundary. | Central policy, delegation, SoD and selected PostgreSQL route enforcement are tested (P4-IAM-001 slices; E-363 through E-385). | Complete route/job/export/UI adoption, federation, distributed invalidation and independent IAM review remain open. |
| Connector posture | Odoo documents synchronization through third-party providers. ERPNext documents importing bank statements rather than a universal live-bank guarantee. | Strict offline CAMT.053 and reference read-only connector contracts are packaged. Governed write-back is an append-only proposal/approval boundary, not a provider acknowledgement. | Live ERP/bank interoperability, provider sandbox evidence and production write-back are not verified. |
| Determinism and lineage | The cited product pages describe workflows but do not publish a directly comparable input/rule/output digest contract. | Stable IDs, exact Decimal policies, strategy/version digests, replay/permutation tests and evidence manifests are implemented in bounded paths. | This is a repository-level contract, not proof that all supported engines or future connectors are equivalent. |
| Runtime scale evidence | The cited official pages do not provide a comparable reproducible benchmark for the workflows above. | A disposable PostgreSQL 16 run completed 10,000 grouped partitions and 24,000 result rows with zero duplicates/residue (E-392); the artifact is explicitly one-host synthetic correctness/concurrency evidence. | It is not a capacity, throughput, soak, HA/DR, or production-sizing claim. |
| Sovereign operation | ERPNext and Fineract publish open-source project documentation; the cited workflow pages do not establish an air-gapped operating profile. | Community local-first/offline operation, strict no-network defaults and bounded file ingestion are documented and tested. | Independent deployment review, multi-site HA/DR and customer-operated key custody remain unverified. |
| Product boundary | Odoo and ERPNext document broad ERP capabilities; Fineract documents a financial-services platform surface. | ReconForge deliberately focuses on financial integrity, reconciliation, exceptions and verifiable evidence alongside source systems. | Breadth should be added only with real use cases, manifests, tests and evidence; do not turn this comparison into an ERP-replacement claim. |

## Decisions this matrix supports

1. Prioritize live-provider sandbox contracts, conformance tests and safe
   write-back acknowledgement before describing a connector as live.
2. Keep the 10K PostgreSQL result labelled as a bounded synthetic runtime
   profile until independent capacity, soak and failure-domain evidence exists.
3. Preserve the local-first control/evidence wedge instead of copying the
   breadth claims of an ERP suite.
4. Keep future public wording tied to a dated evidence ID and the exact tested
   boundary.

## Maintenance

Refresh this document when a first-party source changes, a new ReconForge
evidence ID closes a gap, or an unresolved comparison is no longer meaningful.
The older [competitive capability matrix](competitive-capability-matrix.md)
remains the broader historical assessment; this dated supplement is the narrow
official-source record for the current execution state.
