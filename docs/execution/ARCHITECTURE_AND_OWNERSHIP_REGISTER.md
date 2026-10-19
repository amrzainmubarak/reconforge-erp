# ReconForge Architecture and Ownership Register

Authoritative governance register establishing strict single-workspace concurrency boundaries, file ownership, interface contracts, and change serialization for the single development directory `F:\reconforge-erp`.

---

## 1. Single-Workspace Concurrency Policy

Under the mandatory single-workspace directive (ADR0863 / 2026-10-18):
- All development occurs exclusively in `F:\reconforge-erp`.
- No secondary Git worktrees or external repository clones are permitted.
- The Principal Engineering Lead is the sole authority permitted to stage, commit, push, rebase, or merge repository changes.
- All three specialized subagents collaborate concurrently in the same filesystem through disjoint, non-overlapping file and directory allocations.

---

## 2. Agent Roles and Ownership Allocations

### 2.1 Principal Lead (Central Architectural & Release Authority)
- **Role**: Chief Enterprise Architect, Release Manager, Git Mutation Authority.
- **Exclusive File Ownership**:
  - `reconforge/db/migrations/`
  - `reconforge/platform/`
  - `reconforge/auth/`
  - `reconforge/audit/`
  - `reconforge/api/router.py` (central route integration)
  - `.github/workflows/`
  - `docs/execution/*.md` (central coordination and evidence manifests)
  - Repository-level configuration (`pyproject.toml`, `package.json`, `Makefile`, `Dockerfile`)
- **Integration Invariants**:
  - Serializes all shared migration numbers and schema revisions.
  - Reviews and merges contracts between domains.
  - Executes Level 1, 2, and 3 verification gates.

---

### 2.2 Agent A — Global Finance & Enterprise Data Engineering
- **Role**: Staff Financial Engine Architect & Database Processing Specialist.
- **Exclusive File Ownership**:
  - `reconforge/domain/finance_*.py`
  - `reconforge/domain/intercompany*.py`
  - `reconforge/domain/financial_*.py`
  - `reconforge/domain/fixed_assets.py`
  - `reconforge/domain/receivables.py`
  - `reconforge/domain/payables*.py`
  - `reconforge/domain/operational_fx_tax.py`
  - `reconforge/infrastructure/postgres_finance_*.py`
  - `reconforge/infrastructure/postgres_tax_*.py`
  - `reconforge/infrastructure/sqlite_finance_*.py`
  - `reconforge/infrastructure/sqlite_accounts.py`
  - `reconforge/infrastructure/sqlite_receivables.py`
  - `reconforge/infrastructure/sqlite_payables.py`
  - `reconforge/packs/tax/`
  - `reconforge/packs/country/`
  - `tests/test_*finance*.py`
  - `tests/test_*receivables*.py`
  - `tests/test_*payables*.py`
  - `tests/test_*fixed_assets*.py`
  - `tests/test_*tax*.py`
- **Completed Deliverables**:
  - **Slice A1**: Financial Domain & Country Pack Governance: Formalize Country Coverage Registry (`reconforge/packs/country_registry.py`) and enhance Fixed Asset disposal/impairment accounting in `reconforge/domain/fixed_assets.py` without float arithmetic.
  - **Slice A2**: Treasury Liquidity & Cash Forecasting (Level 1 & Level 2): Deterministic liquidity timeline buckets, basis-point scenario modeling, and stress testing in `reconforge/domain/treasury_liquidity.py`, backed by `reconforge/infrastructure/sqlite_treasury.py`, mounted at `/api/v1/treasury` in `reconforge/api/routes/treasury_liquidity.py`, and verified in `tests/test_api_treasury_liquidity.py`.
- **Current Active Workstream**:
  - **Slice A3**: Intercompany Multi-Entity Elimination and FX Translation Ledger Integration: Expand `reconforge/domain/intercompany_elimination.py` to reconcile paired cross-border trade and reciprocal ledger balances.

---

### 2.3 Agent B — Manufacturing, Supply Chain & Industrial Operations
- **Role**: Principal Industrial Operations & Materials Processing Specialist.
- **Exclusive File Ownership**:
  - `reconforge/domain/manufacturing_*.py`
  - `reconforge/domain/inventory_*.py`
  - `reconforge/domain/procurement_*.py`
  - `reconforge/domain/supplier_returns.py`
  - `reconforge/domain/landed_cost.py`
  - `reconforge/domain/stock_*.py`
  - `reconforge/infrastructure/postgres_manufacturing_*.py`
  - `reconforge/infrastructure/postgres_inventory_*.py`
  - `reconforge/infrastructure/postgres_stock_*.py`
  - `reconforge/infrastructure/sqlite_inventory_*.py`
  - `reconforge/infrastructure/sqlite_manufacturing_*.py`
  - `reconforge/api/routes/manufacturing_bom.py`
  - `tests/test_*manufacturing*.py`
  - `tests/test_*inventory*.py`
  - `tests/test_*procurement*.py`
  - `tests/test_*supplier_returns*.py`
- **Completed Deliverables**:
  - **Slice B1**: Work Center Finite Capacity Planning & Rescheduling: Atomic slot booking, conflict rejection, and calendar shift handling in `reconforge/domain/manufacturing_capacity_scheduling.py`.
  - **Slice B2**: Advanced Multi-Level BOM Explosion & MRP Shortage Netting (Level 1 & Level 2): Indented BOM traversal with cycle detection, scrap factors, and lot-size replenishment in `reconforge/domain/manufacturing_bom_explosion.py`, backed by `reconforge/infrastructure/sqlite_manufacturing_bom.py`, mounted at `/api/v1/manufacturing/bom` in `reconforge/api/routes/manufacturing_bom.py`, and verified in `tests/test_api_manufacturing_bom.py`.
- **Current Active Workstream**:
  - **Slice B3**: Shop Floor Execution & Traceability Genealogy: Complete batch tracking, WIP stage movements, and routing variance accounting in `reconforge/domain/manufacturing_execution_v2.py`.

---

### 2.4 Agent C — Enterprise Applications, UX, Integrations & AI
- **Role**: Staff Enterprise Applications Architect, UI/UX Lead & AI Security Specialist.
- **Exclusive File Ownership**:
  - `reconforge/domain/people_project_payroll.py`
  - `reconforge/domain/crm_*.py`
  - `reconforge/domain/hcm_leave.py`
  - `reconforge/domain/project_*.py`
  - `reconforge/domain/sales_revenue.py`
  - `reconforge/domain/retail_settlement.py`
  - `reconforge/domain/notifications.py`
  - `reconforge/domain/notification_inbox.py`
  - `reconforge/infrastructure/sqlite_hcm_leave.py`
  - `reconforge/infrastructure/sqlite_crm_contracts.py`
  - `reconforge/api/routes/hcm_leave.py`
  - `reconforge/api/routes/crm_contracts.py`
  - `reconforge/ai/`
  - `reconforge/studio/`
  - `apps/web/`
  - `tests/test_*project*.py`
  - `tests/test_*payroll*.py`
  - `tests/test_*crm*.py`
  - `tests/test_*hcm*.py`
  - `tests/test_*ai*.py`
  - `tests/test_*notifications*.py`
- **Completed Deliverables**:
  - **Slice C1**: HCM Employee Leave & Self-Service Workflows (Level 1 & Level 2): `reconforge/domain/hcm_leave.py` with entitlement/absence accounting, backed by `reconforge/infrastructure/sqlite_hcm_leave.py`, mounted at `/api/v1/hcm/leave` in `reconforge/api/routes/hcm_leave.py`, and verified in `tests/test_api_hcm_leave.py`; plus explainable AI auditing in `reconforge/ai/governed_assistant.py`.
  - **Slice C2**: CRM Opportunity Pipeline, Tiered Quotation Approvals & Customer Contracts (Level 1 & Level 2): Weighted pipeline value, maker-checker discount governance, and contract lifecycle in `reconforge/domain/crm_contracts.py`, backed by `reconforge/infrastructure/sqlite_crm_contracts.py`, mounted at `/api/v1/crm/contracts` in `reconforge/api/routes/crm_contracts.py`, and verified in `tests/test_api_crm_contracts.py`.
- **Current Active Workstream**:
  - **Slice C3**: Professional Services Project Costing, Resource Allocation & Milestone Billing: Link contract line items to project work breakdown structures and verified billable timesheets.

---

## 3. Strict Concurrency Rules

1. **No Overlapping Writes**: Subagents must touch only files within their declared ownership. Any file modification outside allocated paths requires an interface request to the Lead.
2. **Deterministic Interfaces**: Cross-domain interactions must happen through typed dataclasses and Protocols in domain models, never direct cross-domain table writes.
3. **Explicit Staging**: Git staging must use exact file paths (`git add <file>`), never `git add .` or `git add -A`.
4. **Isolated Fast Testing**: Each agent executes only Level 1 unit/contract tests for its modified modules. The Lead coordinates Level 2 domain integration and Level 3 release acceptance.
