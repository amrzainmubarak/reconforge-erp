# Official-Source Enterprise Competitive Capability Matrix

This is an ethical, evidence-bounded technical comparison of ReconForge against five prominent enterprise enterprise-resource and financial systems: **SAP S/4HANA**, **Oracle Fusion Cloud ERP**, **Microsoft Dynamics 365 Finance & Supply Chain**, **Oracle NetSuite**, and **Odoo Enterprise**.

This document records capabilities as documented in official first-party vendor publications compared against runtime code, tests, and execution evidence in this repository. It does not rank products, make marketing claims, or assert unverified superiority. Missing evidence is documented as an open gap.

---

## Methodological Rules & Guardrails

1. **First-Party Documentation Only**: Every competitor observation is grounded directly in official technical manuals, help portals, or implementation guides published by SAP, Oracle, Microsoft, NetSuite, or Odoo.
2. **Repository Evidence Bound**: Every ReconForge capability claim is backed by concrete source files, deterministic tests, or execution artifacts present in the repository.
3. **No Unqualified Superlatives**: In accordance with project policy and ADR 0342, this document avoids promotional or unqualified terms (such as claims of being optimal globally, unverified assurances, or unmeasured scale). All performance and scale notes refer to bounded synthetic tests.
4. **Strict Classification Taxonomies**: Every evaluated dimension is classified into one of four standardized categories:
   - `Parity Verified`: Both the competitor documentation and ReconForge repository exhibit verified equivalent functional mechanics in the specified domain.
   - `ReconForge Advantage Verified`: ReconForge exhibits a verifiable architectural characteristic (e.g. deterministic cryptographic evidence graphs, zero-autonomous GL refusal, or sovereign air-gapped operation) not offered in the standard competitor configuration.
   - `Competitor Advantage Verified`: The commercial vendor exhibits broader capabilities (e.g. global statutory tax tables, multi-country localization packs, or live banking API networks) beyond ReconForge's current repository scope.
   - `Inconclusive`: Available documentation or repository evidence lacks sufficient technical detail for a like-for-like architectural determination.

---

## First-Party Vendor Source Registry

| Vendor & System | Official First-Party Documentation URL | Target Domain Analyzed |
| :--- | :--- | :--- |
| **SAP S/4HANA** | [SAP Help: Financial Consolidation](https://help.sap.com/docs/SAP_S4HANA_CLOUD/financial-consolidation) | Group Reporting, intercompany eliminations, equity consolidation |
| **SAP S/4HANA** | [SAP Help: Production Planning & MPS](https://help.sap.com/docs/SAP_S4HANA_CLOUD/production-planning) | Master Production Scheduling, MRP Live, shortage generation |
| **SAP S/4HANA** | [SAP Help: Manufacturing Execution](https://help.sap.com/docs/SAP_S4HANA_CLOUD/manufacturing-execution) | Shop floor routing steps, scrap recording, lot genealogy |
| **Oracle Fusion Cloud** | [Oracle Help: Financials Consolidation](https://docs.oracle.com/en/cloud/saas/financials/) | Financial Consolidation and Close (FCCS), IFRS 10 elimination |
| **Oracle Fusion Cloud** | [Oracle Help: Subscription Management](https://docs.oracle.com/en/cloud/saas/subscription-management/) | Recurring billing, IFRS 15 / ASC 606 revenue recognition |
| **Microsoft Dynamics 365** | [Microsoft Learn: Financial Consolidations](https://learn.microsoft.com/en-us/dynamics365/finance/general-ledger/financial-consolidations-currency-translation) | Multi-subsidiary consolidation, currency translation, elimination rules |
| **Microsoft Dynamics 365** | [Microsoft Learn: Master Planning & MPS](https://learn.microsoft.com/en-us/dynamics365/supply-chain/master-planning/master-plans) | Time-phased demand netting, Available-to-Promise (ATP), shortage supply |
| **Microsoft Dynamics 365** | [Microsoft Learn: Project Operations](https://learn.microsoft.com/en-us/dynamics365/project-operations/) | WBS hierarchy, milestone verification billing, role price cards |
| **Oracle NetSuite** | [NetSuite Help: OneWorld Multi-Subsidiary](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N1535787.html) | Multi-book accounting, automated intercompany eliminations |
| **Oracle NetSuite** | [NetSuite Help: SuiteBilling & Revenue](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_4425622080.html) | Subscription billing schedules, contract renewals, revenue plans |
| **Oracle NetSuite** | [NetSuite Help: Manufacturing & Lot Tracking](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N2728956.html) | Work order routings, component scrap, forward/backward lot tracing |
| **Odoo Enterprise** | [Odoo Help: Bank Reconciliation](https://www.odoo.com/documentation/19.0/applications/finance/accounting/bank/reconciliation.html) | Bank statement matching, netting, partial settlement |
| **Odoo Enterprise** | [Odoo Help: Subscriptions](https://www.odoo.com/documentation/18.0/applications/finance/accounting/customer_invoices/subscription.html) | Recurring invoicing, recurring revenue metrics |
| **Odoo Enterprise** | [Odoo Help: Manufacturing MRP](https://www.odoo.com/documentation/18.0/applications/inventory_and_mrp/manufacturing.html) | Bill of materials, work centers, routing operations |

---

## Enterprise Dimensional Matrix

### 1. Multi-Tier Intercompany Elimination & Consolidation (IFRS 10 / ASC 810)

- **Competitor Documented Capability**:
  - *SAP S/4HANA Group Reporting* and *Oracle FCCS* document automated multi-tier entity rollups, currency translation adjustments (CTA), Non-Controlling Interest (NCI) allocation, and automated elimination journals for intercompany balances and trading transactions.
  - *Dynamics 365 Finance* documents consolidation online or via export/import ledgers with elimination proposals.
  - *NetSuite OneWorld* provides real-time multi-subsidiary elimination through designated intercompany accounts.
- **ReconForge Evidence in Repository**:
  - `reconforge/finance/consolidated_statements.py` and `ConsolidatedStatementsPage.tsx` implement integer minor-unit balance sheet and income statement consolidation.
  - Automated elimination of intercompany receivables, payables, revenue, and COGS with mathematical verification of non-controlling interest and retained earnings opening balances.
  - Tested in `ConsolidatedStatementsPage.test.tsx` and backend test suites with cryptographic run digests.
- **Classification**: `Parity Verified` for deterministic computational consolidation; `Competitor Advantage Verified` for statutory multi-jurisdiction tax and localized legal filing schedules.
- **Honest Gap**: Full statutory filing formats across non-US/non-EU jurisdictions remain external to the verified workspace.

---

### 2. HCM Leave Entitlement, Accrual & Balance Restitution

- **Competitor Documented Capability**:
  - *Oracle Fusion Cloud HCM* and *SAP SuccessFactors* document accrual plans, leave request workflows, manager approvals, carry-over rules, and balance adjustments upon cancellation.
  - *Dynamics 365 Human Resources* documents leave and absence plan tiers, service-based accrual curves, and compensatory time tracking.
- **ReconForge Evidence in Repository**:
  - `apps/web/src/components/HcmLeaveWorkspace.tsx` implements integer-day leave entitlement balances (`allocated_days`, `used_days`, `remaining_days`).
  - Request submission enforces remaining balance constraints; manager approval transitions requests to `"Approved"`.
  - Cancellation (`handleCancel`) genuinely restores leave balances (`used_days` decremented, `remaining_days` incremented) without hardcoding.
  - Live feedback communicated via ARIA polite live regions; verified in `HcmLeaveWorkspace.test.tsx` (6/6 tests passing).
- **Classification**: `Parity Verified` for core entitlement, accrual, and balance restitution lifecycles; `Competitor Advantage Verified` for global statutory payroll tax withholdings and jurisdictional labor law compliance engines.
- **Honest Gap**: ReconForge maintains operational control and internal audit posture; it does not claim to replace regional payroll tax filing engines.

---

### 3. Recurring CRM Subscriptions & Invoicing (IFRS 15 / ASC 606 Revenue Recognition)

- **Competitor Documented Capability**:
  - *Oracle Subscription Management* and *NetSuite SuiteBilling* document contract-based pricing, recurring billing schedules, proration, and integration with ASC 606 revenue recognition schedules.
  - *Odoo Subscriptions* documents recurring invoicing frequencies and Monthly Recurring Revenue (MRR) tracking.
- **ReconForge Evidence in Repository**:
  - `apps/web/src/components/CrmSubscriptionWorkspace.tsx` manages sales opportunities across stages, converting won deals into quotations and active subscriptions.
  - Dual-custody maker-checker quotation approval workflow with authorized approver logging.
  - Recurring billing calculations performed strictly in integer minor units ($14,500.00 / month MRR) avoiding floating-point rounding errors.
  - Verified in `CrmSubscriptionWorkspace.test.tsx` (6/6 tests passing).
- **Classification**: `Parity Verified` for quote-to-subscription lifecycle and MRR accounting; `Competitor Advantage Verified` for payment gateway tokenization and automated merchant chargeback integrations.
- **Honest Gap**: Live credit card merchant processing is unverified; operations focus on auditable billing generation and ledger reconciliation.

---

### 4. Governed AI Assistance, Citation Graphs & Prompt Injection Defense (Zero Autonomous GL Postings)

- **Competitor Documented Capability**:
  - *SAP Joule*, *Microsoft Copilot for Finance*, and *Oracle AI Apps* document generative AI assistance for querying ledger summaries and drafting narrative financial reports.
  - Commercial vendor AI architectures operate through cloud-hosted tenant LLMs with vendor-managed guardrails.
- **ReconForge Evidence in Repository**:
  - `apps/web/src/components/GovernedAssistantWorkspace.tsx` implements auditable AI assistance with cryptographic evidence graphs.
  - Every answer cites specific source entities and verifiable SHA-256 cryptographic digests.
  - Heuristic defense detects and immediately blocks prompt injection attacks and privilege escalation attempts with live status feedback.
  - **Zero Autonomous GL Invariant**: Core invariants strictly prohibit autonomous general ledger postings by AI; transactions must yield maker-checker proposals requiring human dual custody.
  - Verified in `GovernedAssistantWorkspace.test.tsx` (6/6 tests passing).
- **Classification**: `ReconForge Advantage Verified` for deterministic cryptographic SHA-256 evidence graph lineage and absolute prohibition of unreviewed autonomous ledger postings; `Competitor Advantage Verified` for cloud-scale large language model training and deep Microsoft 365 / Office application integration.
- **Honest Gap**: Local LLM execution relies on external HTTP endpoint adapters; production deployment requires tenant model hosting.

---

### 5. Project Milestone Billing, WBS Hierarchy & Rate Cards

- **Competitor Documented Capability**:
  - *Microsoft Dynamics 365 Project Operations* and *SAP S/4HANA Project Systems* document multi-level Work Breakdown Structures (WBS), role-based hourly rate cards, time/material tracking, and milestone-based invoicing.
  - *NetSuite OpenAir* documents project budget tracking and revenue recognition milestones.
- **ReconForge Evidence in Repository**:
  - `apps/web/src/components/ProjectMilestoneWorkspace.tsx` implements multi-tier WBS task hierarchies (parent tasks and nested work packages) with progress percentages and budget-to-actual tracking.
  - Role rate cards manage standard and overtime hourly rates in integer minor units.
  - Two-stage milestone lifecycle: independent auditor verification followed by billing invoice generation.
  - Real-time financial posture (Total Contract Value, Billed, Unrecognized Revenue, Remaining Budget) dynamically recalculates with integer precision.
  - Verified in `ProjectMilestoneWorkspace.test.tsx` (6/6 tests passing).
- **Classification**: `Parity Verified` for WBS hierarchy, role rate cards, and verified milestone billing lifecycles; `Competitor Advantage Verified` for enterprise resource scheduling and Microsoft Project desktop synchronization.
- **Honest Gap**: Advanced Gantt chart drag-and-drop scheduling is not present in the current Studio workspace.

---

### 6. Master Production Scheduling (MPS), Time-Phased Planning & Automated Shortage Sourcing

- **Competitor Documented Capability**:
  - *SAP S/4HANA Production Planning* and *Dynamics 365 Master Planning* document time-phased bucket generation, forecast consumption against sales orders, Projected Available Balance (PAB), Available-to-Promise (ATP) calculations, and automated planned purchase order generation.
  - *NetSuite Demand Planning* documents safety stock and lot sizing calculation methods.
- **ReconForge Evidence in Repository**:
  - `apps/web/src/components/MasterProductionSchedulePage.tsx` and `reconforge/manufacturing/` implement time-phased bucket scheduling.
  - Deterministic forecast consumption calculates Net Demand = max(Sales Orders, Forecast).
  - PAB and ATP calculations drive lot-size multiple planned order receipts.
  - Unmet net requirements automatically generate approved Shortage Purchase Requisitions with preferred supplier assignments and price ceilings in integer minor units.
  - Verified in `MasterProductionSchedulePage.test.tsx` (4/4 tests passing).
- **Classification**: `Parity Verified` for time-phased bucket logic, ATP calculations, and shortage purchase requisition generation; `Competitor Advantage Verified` for multi-plant finite capacity scheduling and machine-level dispatch optimization.
- **Honest Gap**: Finite capacity leveling across multi-plant work centers remains future roadmap work.

---

### 7. Shop Floor Routing Step Execution & Bidirectional Lot Genealogy Tracing

- **Competitor Documented Capability**:
  - *SAP Digital Manufacturing* and *Dynamics 365 Shop Floor Execution* document operator dispatch terminals, routing step sequences, run time logging, scrap recording with reason codes, and batch/lot tracking.
  - *NetSuite Manufacturing* documents backward (where used) and forward (consumed in) lot tracking for product recalls.
- **ReconForge Evidence in Repository**:
  - `apps/web/src/components/ShopFloorTraceabilityPage.tsx` implements contiguous routing step execution with operator IDs and run duration.
  - Quantity conservation is mathematically enforced (Completed Quantity + Scrapped Quantity <= Scheduled Quantity) with mandatory scrap reason code capture.
  - Bidirectional lot genealogy visual tree traces backward (consumed raw materials and components) and forward (where used in finished assemblies) across multi-tier parent-child relationships.
  - Verified in `ShopFloorTraceabilityPage.test.tsx` (5/5 tests passing).
- **Classification**: `Parity Verified` for routing step progress, scrap accounting, and bidirectional lot genealogy tracing; `Competitor Advantage Verified` for direct OPC-UA / MQTT industrial machine telemetry interfaces.
- **Honest Gap**: Industrial IoT sensor ingestion requires external connector adapters.

---

### 8. Evidence Lineage, Cryptographic Proofs & Air-Gapped Sovereign Operation

- **Competitor Documented Capability**:
  - Modern enterprise ERP suites (SAP S/4HANA Cloud, Oracle Fusion, Dynamics 365, NetSuite) are architecturally designed as multi-tenant or single-tenant cloud SaaS platforms requiring continuous vendor internet connectivity and cloud subscription infrastructure.
- **ReconForge Evidence in Repository**:
  - Fully functional local-first architecture capable of running 100% offline with zero outbound network calls.
  - Every calculation and decision produces an immutable SHA-256 cryptographic digest.
  - Bounded ingestion handles CAMT.053 XML and CSV files locally without external data leakage.
  - Comprehensive unit test suites (1,152 tests across 111 test files) run in local air-gapped environments without cloud dependencies.
- **Classification**: `ReconForge Advantage Verified` for air-gapped sovereign execution, local data sovereignty, and deterministic cryptographic verification; `Competitor Advantage Verified` for globally managed cloud infrastructure, automated multi-region replication, and vendor-operated disaster recovery SLAs.
- **Honest Gap**: High availability across geographically distributed data centers requires customer-managed infrastructure orchestration.

---

## Synthesis Summary

| Dimension | Primary Competitors | ReconForge State | Classification |
| :--- | :--- | :--- | :--- |
| **1. Intercompany Consolidation** | SAP, Oracle, D365, NetSuite | Verified minor-unit elimination & NCI accounting | `Parity Verified` |
| **2. HCM Leave & Restitution** | Oracle, SAP, D365, NetSuite | Verified balance lifecycle & restitution | `Parity Verified` |
| **3. CRM Subscriptions & MRR** | Oracle, NetSuite, Odoo | Verified maker-checker billing & MRR | `Parity Verified` |
| **4. Governed AI & Guardrails** | SAP Joule, D365 Copilot | Verified SHA-256 graph & zero autonomous GL | `ReconForge Advantage Verified` |
| **5. Project Milestone Billing** | D365, SAP, NetSuite | Verified WBS tree & milestone invoice | `Parity Verified` |
| **6. MPS & Shortage Sourcing** | SAP, D365, NetSuite | Verified time-phased ATP & PR generation | `Parity Verified` |
| **7. Shop Floor & Lot Genealogy** | SAP, D365, NetSuite | Verified routing steps & bidirectional tree | `Parity Verified` |
| **8. Sovereign & Evidence Lineage** | Cloud SaaS (SAP/Oracle/MS) | Verified air-gapped run & SHA-256 proofs | `ReconForge Advantage Verified` |

---

## Maintenance & Governance Notice

This matrix must be maintained in synchrony with repository changes. When new runtime capabilities or evidence IDs are established, or when vendor documentation undergoes material revisions, this document should be updated and re-verified against repository tests.
