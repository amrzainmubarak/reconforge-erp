# Original User Request

## 2026-10-19T02:46:00Z

# Teamwork Project Prompt — ReconForge Enterprise ERP v1.0 Execution

ReconForge is an open-source, local-first Financial Integrity & Operations Control Platform being advanced to a world-class, production-qualified Enterprise ERP v1.0 suite.
The mission is to close all architectural, operational, and functional gaps across Global Finance, Advanced Manufacturing, HCM/Payroll, CRM/Services, and Governed Business AI through deterministic, source-bound execution without worktrees or floating-point rounding errors.

Working directory: F:\reconforge-erp
Integrity mode: benchmark

The team is requested as three specialized domain agents (Agent A: Global Finance, Agent B: Manufacturing/Supply Chain, Agent C: Enterprise Apps/UX/AI) supervised by a Principal Architectural Authority in a single shared workspace.

## Requirements

### R1. Global Finance, Tax, Treasury & Multi-Entity Consolidation (Agent A)
- Implement multi-company consolidation, intercompany eliminations, and FX translation reconciliations without floating-point arithmetic using strict MinorMoney integer minor-unit arithmetic and versioned currency registries.
- Complete fixed asset impairment and multi-register disposal accounting (reconforge/domain/fixed_assets.py) with exact gain/loss GL line generation.
- Expand country-specific statutory packs through the versioned Country Coverage Registry (reconforge/packs/country_registry.py) with verified date windows, e-invoice schemas, and tax calculation rules.
- Resolve M7.7 multi-currency and tax-inclusive sales return integration contracts with independent financial proof and native PostgreSQL verification.

### R2. Advanced Manufacturing, Supply Chain & Industrial Operations (Agent B)
- Implement Work Center capacity planning, shift calendars, and finite slot reservations in reconforge/domain/manufacturing_capacity_scheduling.py with atomic booking, conflict rejection, and reschedule operations.
- Build multi-level BOM explosion, revision management, and component substitution logic.
- Expand MRP and demand planning to generate governed shortage replenishment purchase requisitions without duplicate supply generation.
- Enforce strict mass/cost conservation invariants: Material + Labor + Overhead = Finished Goods + Scrap + Remaining WIP with zero integer leakage.

### R3. Enterprise Applications, HCM, CRM, UX & Governed Business AI (Agent C)
- Build HCM Employee Leave & Absence Management (reconforge/domain/hcm_leave.py) with exact accrual arithmetic, submission/cancellation lifecycle, and maker-checker approval workflows.
- Implement CRM opportunity pipeline, contract lifecycle, and subscription prorated billing.
- Expand bilingual English (LTR) and Arabic (RTL) Studio user journeys conforming to WCAG 2.1 AA accessibility standards without layout truncation or broken forms.
- Build permission-aware, explainable AI assistant guardrails (reconforge/ai/governed_assistant.py) enforcing read-only boundary checks, confidence thresholds, source citation graphs, and strict human maker-checker envelopes with zero autonomous GL postings.

### R4. Single-Workspace Concurrency & CI Gate Governance (Principal Architectural Authority)
- Enforce strict single-directory execution in F:\reconforge-erp with zero secondary worktrees or development clones.
- Maintain disjoint file allocations per agent as specified in docs/execution/ARCHITECTURE_AND_OWNERSHIP_REGISTER.md.
- Serialize all Git staging, commits, branch management, migration numbering, and shared database schema modifications exclusively through the Principal Lead.
- Optimize CI verification into a three-tiered pipeline: Level 1 Fast Local Gate (< 30s), Level 2 Domain Integration Gate (< 3m), and Level 3 Release Acceptance Gate.

## Acceptance Criteria

### Financial & Arithmetic Invariants
- 100% of monetary, tax, and inventory calculations use integer minor units or scaled decimals; zero float instances exist in financial effect paths.
- Every journal entry strictly balances: Debit == Credit in both transaction and functional currencies.
- Additive FIFO restitution correctly restores original consumed layers upon customer return without repricing historical transactions.

### Operational & Domain Integrity
- Work Center finite capacity scheduling rejects conflicting overlapping work orders atomically.
- Leave requests consume verified entitlements and replenish balances on approved cancellation without negative balance leakage.
- AI assistant cannot execute or propose unquoted financial postings, bypass tenant isolation, or execute commands without human approval.

### Security, Performance & Architecture
- PostgreSQL FORCE RLS is verified on all tenant-partitioned entities with zero cross-workspace data leakage.
- Level 1 fast local gate passes in under 30 seconds (ruff check, targeted mypy, focused unit tests).
- Zero uncoordinated concurrent file writes occur across agents.
- Single workspace in F:\reconforge-erp is preserved with zero newly created worktrees.


## 2026-10-19T12:40:41Z

# Teamwork Project Prompt — Draft

> Status: Launched
> Goal: Craft prompt → get user approval → delegate to teamwork_preview
> Requested team: Full multi-agent team (Principal Lead coordinating Agent A [Finance/Tax/Treasury], Agent B [Manufacturing/SCM], Agent C [HCM/CRM/Projects/UX/AI])

Complete 100% of ReconForge's declared Enterprise ERP v1.0 functional scope, prove architectural integrity across every business domain, qualify the complete platform for real production deployment, and validate competitive advantages against leading enterprise ERP systems.

Working directory: F:\reconforge-erp
Integrity mode: development

## Context & Baseline
- Repository: `https://github.com/amrzainmubarak/reconforge-erp`
- Working Directory Policy: Strictly inside `F:\reconforge-erp`. No new Git worktrees or clones.
- Active Branch: `amr/enterprise-erp-v1-execution-20261018` (HEAD verified at `9b6aac61`)
- Database Baseline: PostgreSQL migration 0151, SQLite migration 57, fail-closed PostgreSQL enterprise mode.

## Requirements

### R1. Agent A — Global Finance, Tax, Treasury & Corporate Accounting
Complete and integrate all remaining finance capabilities:
- General Ledger & financial dimensions, AR/AP and settlements, multi-currency & FX accounting.
- Banking & reconciliation, treasury & liquidity, cash flow reporting, financial forecasting.
- Accruals/deferrals, revenue recognition, fixed assets & depreciation, financial close & reopening.
- Intercompany transactions, eliminations, group consolidation, and consolidated financial statements.
- Country tax packs (Egypt, KSA, UAE, UK, US) and statutory reporting.
- Payroll-to-GL and project/manufacturing accounting integration.
- Mandatory: Canonical posting authority preserved; no shadow GLs or unverified posting shortcuts.

### R2. Agent B — Advanced Manufacturing, Planning & Supply Chain
Complete and integrate all remaining manufacturing & supply chain capabilities:
- Engineering BOM & revisions, product configuration, substitutions.
- MPS and MRP, production scheduling, finite-capacity planning, work centers and routings.
- Production orders, shop-floor execution, material reservations and issuing.
- WIP accounting, labor and overhead allocation, production variances, scrap, rework.
- Quality inspections, lot and serial genealogy, multi-warehouse & multi-plant inventory costing/reconciliation.
- Procurement replenishment, supplier sourcing, equipment and maintenance integration.
- Mandatory: Strict quantity conservation and authoritative inventory layer cost transfers.

### R3. Agent C — HCM, CRM, Projects, Enterprise UX & Governed AI
Complete and integrate all remaining workforce, customer, project, and interface capabilities:
- HCM employee lifecycle, recruitment, onboarding, leave, attendance, shift management, payroll workflows, employee self-service.
- CRM leads, opportunities, quotation lifecycle, customer contracts, subscriptions, renewals, support tickets, SLAs.
- Project management, resource allocation, timesheets, milestone billing, project profitability.
- Arabic (RTL) / English (LTR) responsive Studio UX with verified accessible user journeys.
- Enterprise document management, workflow approvals (maker-checker), notifications, search, audit trail.
- Governed Enterprise AI: permission-aware data access, grounded recommendations, mandatory human approval for financial/control actions.

### R4. Platform Architecture & Enterprise Security
- Strict single-directory operation in `F:\reconforge-erp` with serialized writes and disjoint file ownership.
- Maintain PostgreSQL FORCE RLS, strict tenant/workspace/entity isolation, and connection security.
- Fail-closed enterprise mode when PostgreSQL is unavailable (SQLite reserved for Community/local mode).
- Durable job engine for imports, matches, reports, and exports with checkpoints and idempotency.

### R5. Complete End-to-End Business Lifecycles & Production Qualification
Execute and qualify complete end-to-end operational cycles:
- Manufacturing: Demand → MPS → MRP → Capacity → Procurement → Receipt → Reservation → Production → Shop Floor → Quality → FG → Inventory → GL.
- Finance: Transaction Source → Authorized Posting → GL → AR/AP → Settlement → Bank Reconciliation → FX/Tax → Close → Statements → Consolidation → Audit.
- HCM/Payroll: Recruitment → Employee → Contract → Attendance → Leave → Payroll → Approval → Payment → GL → Settlement.
- Sales & CRM: Lead → Opp → Quote → Approval → Contract → Order → Fulfillment → Invoice → Collection → Return.
- Projects: Contract → Plan → Resources → Timesheets → Costing → Milestone Approval → Invoice → AR → Payment → Profitability.

## Acceptance Criteria

### Gate F1: Functional Completion
- [ ] 100% of declared mandatory Enterprise ERP v1.0 capabilities verified complete in `ENTERPRISE_COMPLETION_MASTER_MATRIX`.
- [ ] Every capability backed by canonical data, migratable persistence, authorized APIs, and working React Studio journeys.
- [ ] No unfinished mandatory scope silently removed, downgraded, or marked complete without implementation.

### Gate F2: Architectural & Financial Integrity
- [ ] Double-entry bookkeeping invariants enforced (zero-sum, minor units/scaled decimal, strict currency conversion).
- [ ] Canonical posting lifecycle enforced with maker-checker and period-close controls; zero bypasses.
- [ ] PostgreSQL FORCE RLS tenant isolation verified under hostile context-switching and connection-pooling tests.
- [ ] Transaction atomicity, concurrency safety, deadlock handling, and idempotency verified.

### Gate P1: Production Qualification
- [ ] Versioned PostgreSQL migrations execute cleanly forward, verify schema integrity, and support backup/restore recovery.
- [ ] Enterprise PostgreSQL mode fails closed if required database services or credentials are not present.
- [ ] Security qualification passes: zero unresolved P0/P1 vulnerabilities, secrets hygiene, audit logging immutable.
- [ ] Background job engine survives worker interruptions and resumes safely from checkpoints.

### Gate C1: Competitive Validation & Reporting
- [ ] Sourced competitive capability matrix comparing ReconForge to SAP S/4HANA, Oracle Fusion, NetSuite, Dynamics 365, and Odoo.
- [ ] High-volume benchmarks executed and documented with reproducible environment specs, wall-clock time, memory, and throughput.
- [ ] Country coverage register accurately reflects verified statutory capabilities for Egypt, KSA, UAE, UK, and US without unverified compliance claims.
- [ ] Final release candidate and comprehensive completion report prepared.
