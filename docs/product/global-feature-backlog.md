# Global Feature Backlog

This backlog is a planning contract, not a capability list. Status labels prevent planned work from being read as released behavior.

## Status legend

- **Implemented** — working code exists in the repository and is covered by tests or established smoke commands.
- **Foundation** — partial models/services/UI/contracts exist, but the area is not complete ERP functionality.
- **This slice** — delivered only as the experimental modern Studio shell or synthetic demo-data bridge.
- **Planned** — no complete supported implementation; requires a future PR.
- **Deferred** — intentionally delayed because security, legal, deployment, or domain prerequisites are not ready.

## A. ERP Core

| Capability | Status | Delivery note |
| --- | --- | --- |
| Organizations, companies, branches, departments | Foundation | Governed organization/entity/branch services, RBAC, audit events, API/CLI, and snapshot now exist; departments remain planned. |
| Multi-company | Foundation | Governed organizations/entities, deterministic translation, a non-posting effective-ownership/NCI/balanced-elimination worksheet, and a local SQLite verified-worksheet close lifecycle with maker-checker approval, exact control-journal effects, and lock/reopen evidence exist; persisted ownership masters, acquisition policy, PostgreSQL/API/UI parity, live providers, write-back, and statutory statements remain planned. |
| Multi-currency | Foundation | Versioned currency precision and an operator-supplied, source-bound period-rate translation artifact exist; live rates, functional-currency remeasurement, posting, and statutory policy assurance remain planned. |
| Multi-language | This slice | English/Arabic client dictionary foundation only. |
| Arabic + English support | This slice | UI shell translation foundation; no claim of complete accounting localization. |
| RTL support | This slice | Layout direction and RTL visual testing for the dashboard shell. |
| Fiscal years and accounting periods | Foundation | Non-overlapping fiscal periods and controlled status metadata exist; source-ERP posting locks and advanced calendars remain planned. |
| Numbering sequences | Planned | Requires company-scoped concurrency and migration design. |
| Contacts, customers, suppliers | Foundation | Canonical examples exist; master-data lifecycle is planned. |
| Product and service catalog | Foundation | Governed local stock/consumable/service item references now exist; pricing, variants, sales/purchase lifecycle, and a general ERP catalog remain planned. |
| Units of measure | Foundation | Governed local units with fixed zero-to-six-place quantity precision now exist; conversion graphs remain planned. |
| Taxes and VAT | Planned | No statutory calculation or filing claim. |
| Approval workflows | Foundation | DB-backed approval metadata and workflow state machine exist. |
| Attachments and document management | Foundation | Evidence/attachment metadata patterns exist; general DMS is planned. |
| Notes, comments, activity timeline | Foundation | Review notes and audit events exist; general activity model is planned. |
| Notifications and reminders | Planned | Local notification abstraction before any email/push provider. |
| Import/export center | Foundation | CSV/XLSX readers, mappings, DB bridge and exports exist; unified UI is planned. |
| Global search | This slice | Command/search UI shell over available navigation only. |
| Command palette | This slice | Keyboard-accessible navigation/quick-action shell. |
| User preferences | This slice | Browser-local theme, density and accessibility preferences; server persistence is planned. |

## B. Finance

| Capability | Status | Delivery note |
| --- | --- | --- |
| Chart of accounts | Foundation | Governed charts, hierarchical accounts, types, normal balance, activity and posting flags are implemented locally; statutory/localized templates are planned. |
| General ledger | Foundation | Balanced multi-line local control entries with immutable Validated lines exist; ReconForge does not post to source ERPs or claim a statutory ledger. |
| Journals and journal entries | Foundation | Organization-scoped journal definitions coexist with backward-compatible export-based policy records; numbering and ERP writeback are planned. |
| Trial balance | Foundation | Validated local control-ledger aggregation and existing export import/reconciliation services exist; financial statements are planned. |
| Balance sheet, P&L, cash flow | Planned | Reporting definitions require ledger semantics and lineage. |
| Accounts receivable/payable | Planned | Export controls may precede transactional subledgers. |
| Customer invoices/vendor bills | Foundation | Canonical export data and control checks exist; transactional lifecycle is planned. |
| Payments | Planned | Payment abstraction and reconciliation come before execution. |
| Bank accounts/reconciliation | Planned | Generic bank-statement import and deterministic matching are the safe first steps. |
| Fixed assets/depreciation | Foundation | Control pack exists; asset register and depreciation engine are planned. |
| Budgets | Planned | Budget records and variance reporting require company/period/dimension primitives. |
| Cost centers/dimensions/projects/departments | Foundation | Governed dimensions/values and required-per-line enforcement exist; organization-specific hierarchies and allocations are planned. |
| Intercompany | Foundation | DB-backed matching/case/settlement metadata exists. |
| Month-end close | Implemented | Local JSON and DB-backed close foundations with reports and Studio views. |
| Account reconciliation | Foundation | DB-backed lifecycle, templates and reporting exist; broader policy support is planned. |
| Variance analysis | Implemented | Local period comparison and threshold reports exist. |
| Audit trail | Foundation | Append-only audit events and review history exist across selected workflows. |
| Finance control matrix | Implemented | Rule-pack-derived exports with explicit metadata boundaries. |
| Evidence binder | Implemented | Local files, registers and checksum/provenance aids. |
| SoD checks | Foundation | Known-user creator/reviewer separation exists for selected workflow, Finance Core, inventory movement, count, and FIFO-valuation actions; configurable conflict catalogs remain planned. |
| Exception management | Foundation | File review workflow and DB-backed unified exception queue exist. |

## C. Sales and CRM

Leads, opportunities, pipeline, activities, quotes, sales orders, contracts, subscriptions, customer portal foundation, price lists, discounts, sales targets and sales analytics are **planned**. Customer/invoice export examples provide control inputs, not transactional CRM. The first credible slice should define customer account, lead, opportunity and activity models with permissions, audit events and synthetic APIs before adding pages.

## D. Purchasing and Suppliers

| Capability | Status | Delivery note |
| --- | --- | --- |
| Supplier, RFQ, purchase order, receipt, vendor bill | Foundation | Export data/control coverage exists; transactional services are planned. |
| Three-way matching | Foundation | Purchase-to-pay control pack and matching primitives exist; dedicated exception model is planned. |
| Supplier performance | Planned | Requires purchase/receipt/quality history. |
| Supplier portal foundation | Deferred | Identity and authorization design must come first. |
| Contracted pricing | Planned | Requires supplier/product/company masters. |
| Reorder rules | Foundation | Exact item/location thresholds and deterministic advice exist; supplier selection, demand planning, RFQs, POs, and automatic replenishment remain planned. |

## E. Inventory and Warehouse

| Capability | Status | Delivery note |
| --- | --- | --- |
| Warehouses, locations, stock moves | Foundation | Entity-scoped warehouses, hierarchical locations, and a governed local exact-quantity movement ledger now exist; it is not the source ERP's authoritative stock ledger. |
| Receipts, deliveries, transfers, adjustments, cycle counts | Foundation | Local movements plus immutable single-location count snapshots, completed-line submission, independent approval, and Draft variance adjustment generation exist; blind counts, freezes, waves, and mobile execution remain planned. |
| Lots, serials, barcodes, variants | Foundation | Local lot/serial references and posting constraints exist; barcode workflows and product variants remain planned. |
| FIFO valuation foundation | Foundation | Exact local receipt costs, chronological FIFO layers/consumptions, immutable approval evidence, exact whole-valuation reversal through a Posted mirror movement, and balanced Finance Core Draft bridges exist; AVCO, landed cost, manufacturing costing, partial/chained reversal, automatic validation, and ERP writeback do not. |
| Inventory aging | Foundation | WIP/exception aging patterns exist; stock aging report is planned. |
| Stock-to-GL reconciliation | Implemented | Deterministic export-based matching with reports and tests. |
| Slow-moving inventory | Planned | Requires dated stock layers/history. |
| Negative stock detection | Foundation | Protected locations block negative posting; allowed-negative locations produce deterministic exceptions, alongside existing export controls. |
| Multi-warehouse controls | Foundation | Warehouse/location masters, transfers, exact on-hand, and local exceptions exist; replenishment and logistics execution remain planned. |

## F. Manufacturing and Workshop

| Capability | Status | Delivery note |
| --- | --- | --- |
| BOM, routing, work centers, work orders | Foundation | Work-order export and control models exist; planning/execution masters are planned. |
| MRP and capacity planning | Planned | No production-planning engine is claimed. |
| WIP | Implemented | Export-based WIP aging and work-order reconciliation. |
| Subcontracting | Planned | Requires purchasing, BOM and receipt foundations. |
| Quality checks, scrap, maintenance | Foundation | Control-pack coverage exists; transactional services are planned. |
| Spare parts and old-part returns | Implemented | Export-based workshop controls and synthetic examples. |
| Workshop service flows | Foundation | Domain control packs and reports exist; full service-order lifecycle is planned. |
| Fleet maintenance and dealership service controls | Foundation | Dedicated control packs exist. |

## G. Projects and Services

Projects, tasks, timesheets, issues, milestones, project profitability, billing from timesheets, service contracts, SLA foundations, helpdesk/tickets and knowledge base are **planned**. Existing service-contract and project-profitability control concepts can seed requirements, but no end-to-end project ERP is claimed.

## H. HR

Employees and departments are **foundation/planned** master data. Attendance, leave, expenses, recruitment, performance reviews and employee asset assignment are **planned**. Payroll is **deferred to a foundation-only design** until jurisdiction, privacy, permissions and calculation boundaries are explicit. HR/payroll controls may analyze user-provided exports before ReconForge ever calculates payroll.

## I. POS and Commerce

POS session, product catalog, cart/checkout demo, payment abstraction, eCommerce storefront, website/CMS, order fulfillment and returns are **planned**. POS cash and eCommerce order control packs may be implemented as export-based checks first. No payment processing or storefront hosting is currently claimed.

## J. Reporting and BI

| Capability | Status | Delivery note |
| --- | --- | --- |
| Executive dashboard and KPI cards | Implemented / This slice | Existing generated dashboard plus modern synthetic shell. |
| Drill-down reports | Foundation | Studio/report links exist; modern client drill-downs are planned. |
| Saved views | Planned | Requires identity/preferences contract. |
| Report builder foundation | Planned | Must preserve metric lineage and safe templating. |
| CSV/XLSX/PDF/HTML exports | Foundation | CSV/XLSX/HTML are established; PDF coverage is selective/planned. |
| Scheduled reports | Deferred | Local scheduler/security/operability design required. |
| Metrics lineage | Foundation | DB-backed metric definitions and API endpoint exist. |
| Data quality dashboard | Planned | Validators and mapping reports provide inputs. |
| Period comparison | Implemented | Local comparison and variance outputs exist. |

## K. Workflow / BPM / Low-Code

| Capability | Status | Delivery note |
| --- | --- | --- |
| Workflow definitions and state machines | Foundation | Typed DB-backed workflow service exists. |
| Approval chains | Foundation | Approval metadata exists; configurable chains are planned. |
| Form builder and field customization metadata | Planned | Requires schema, validation and migration design. |
| Custom objects | Planned | Depends on module/data dictionary decisions. |
| Rule engine integration | Implemented | Deterministic YAML rule engine with safe operators. |
| Automation triggers | Planned | Local event/authorization model first. |
| Webhooks | Deferred | Outbound network behavior must be optional, explicit and secured. |
| Event bus | Planned | Start with in-process typed domain events and outbox semantics. |

## L. AI / Intelligence

| Capability | Status | Delivery note |
| --- | --- | --- |
| Local-first explanation engine | Implemented | Deterministic/offline explanation foundations. |
| Optional provider-based assistant | Deferred | Must be opt-in, redacted, policy-controlled and unnecessary for core workflows. |
| Natural-language search | Planned | Local index and explicit data boundary first. |
| Exception explanation and control recommendation | Foundation | Deterministic explanations exist; recommendations remain advisory. |
| Reconciliation suggestions | Foundation | Explainable match candidates exist; human review remains authoritative. |
| Anomaly detection | Planned | Prefer deterministic/statistical models with reproducibility. |
| Risk scoring | Implemented | Rule/risk models and explanations exist. |
| No paid API required for core workflows | Implemented constraint | Must remain true. |
| No sensitive ERP data sent externally by default | Implemented constraint | External providers remain opt-in future work only. |

## M. Platform and Developer Ecosystem

| Capability | Status | Delivery note |
| --- | --- | --- |
| Plugin architecture/module registry | Foundation | A read-only registry now exposes shipped local capability metadata and validates dependencies/migrations; dynamic third-party activation and lifecycle hooks remain planned. |
| Control-pack registry | Foundation | Filesystem packs and validation exist; discovery/version catalog is planned. |
| Connector SDK | Foundation | Export adapter interface exists; no live credentialed connector SDK claim. |
| Python SDK | Foundation | Public Python package APIs exist but are not yet a separately versioned SDK. |
| JavaScript/TypeScript SDK | Planned | Generate from stable OpenAPI/contracts later. |
| OpenAPI docs | Foundation | FastAPI generates local OpenAPI; committed contract/generation docs are planned. |
| Webhooks/event bus | Deferred / Planned | See workflow section. |
| CLI scaffolding: module/control pack/connector | Planned | Control-pack templates exist through docs/commands; generators are future work. |
| Example apps | This slice | Modern Studio is the first TypeScript client example. |
| Integration tests | Foundation | Python API/CLI integration tests exist; cross-stack tests are added incrementally. |
| Extension docs | Foundation | Plugin and control-pack docs exist; module SDK docs are planned. |

## Prioritization rules

1. Preserve local-first export workflows and existing CLI behavior.
2. Build shared company/period/currency/auth/audit primitives before domain breadth.
3. Prefer export-based control coverage before transactional ERP write paths.
4. Require typed contracts, permissions, audit events, migrations, synthetic data and tests for each module.
5. Label experimental UI and foundations visibly.
6. Do not add external network calls, telemetry, cloud storage or paid APIs to core workflows.
