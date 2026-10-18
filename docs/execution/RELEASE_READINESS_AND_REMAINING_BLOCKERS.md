# ReconForge Release Readiness and Remaining Blockers

Authoritative release readiness criteria, capability closure roadmap, and blocking issues tracking toward ReconForge Enterprise ERP v1.0.

---

## 1. Release Milestone Definitions

In accordance with Section 13 of the Engineering Protocol:
- **Functional Completion**: All declared core business workflows across Finance, Manufacturing, HCM, CRM, Operations, and AI are implemented end-to-end with verified UI journeys, database contracts, and independent oracles.
- **Production Qualification**: Requires staging verification, failure drills, disaster recovery with measured RPO/RTO, performance qualification under realistic multi-user load, and dependency supply-chain security qualification.

---

## 2. Capability Closure Status Summary

| Workstream | Domain Scope | Status | Key Completed Capabilities | Primary Remaining Deliverables |
| --- | --- | --- | --- | --- |
| **Agent A** | Global Finance & Accounting | **IN PROGRESS** | M7.1–6, M7.8 (Partial returns, FIFO restitution, AR settlement, refunds, reversals), Fixed asset depreciation | M7.7 Tax/FX return contracts; D2.10 Asset disposal/impairment; D2.13 Country Coverage Registry; D2.3 Intercompany elimination |
| **Agent B** | Manufacturing & Supply Chain | **IN PROGRESS** | ME1/ME2 actual costing, BOM integer expansion, scrap disposition, multi-stage routing, basic shortage detection | D1.1-D1.2 BOM revisions and Work Center capacity calendar; D1.3-D1.4 MRP multi-level explosion and netting; D1.7 Material reservations |
| **Agent C** | Enterprise Apps, UX & AI | **IN PROGRESS** | Wage and time contracts, basic project time billing, bilingual RTL web foundation, basic outbox/notification | D3.4 Leave & Absence management / ESS; D4.1-D4.2 CRM quotation and customer contracts; D6.1 Permission-aware explainable AI assistant |

---

## 3. Active Blockers and Engineering Resolutions

### Blocker 1: M7.7 Tax / Foreign-Currency Return Integration
- **Context**: Bounded M7 v1/v2 customer returns are verified complete for zero-tax functional-currency contracts. Multi-currency and tax-inclusive sales return contracts exist in isolation but require finalized native integration tests.
- **Owner**: Agent A (with Lead coordination).
- **Resolution Plan**: Complete native transaction contract verifying tax reversal and realized FX gain/loss upon return credit issuance.

### Blocker 2: Work Center Capacity Contention & Material Reservation
- **Context**: Work orders currently assume infinite capacity for work centers; concurrent work orders can double-book routing operations.
- **Owner**: Agent B.
- **Resolution Plan**: Implement capacity slot reservation in `manufacturing_supply_plan.py` ensuring atomic booking/release with deterministic conflict rejection.

### Blocker 3: Employee Leave Entitlement & Self-Service Approval Workflow
- **Context**: Time tracking and wage calculation exist, but employee leave accruals, absence requests, and maker-checker manager approvals lack an integrated domain contract.
- **Owner**: Agent C.
- **Resolution Plan**: Create `reconforge/domain/hcm_leave.py` with exact accrual arithmetic, leave balance deductions, and cancellation restoration.

### Blocker 4: Permission-Aware AI Guardrails & Audit Verification
- **Context**: AI models must never autonomously post GL transactions or bypass SoD controls.
- **Owner**: Agent C.
- **Resolution Plan**: Implement `reconforge/ai/governed_assistant.py` enforcing read-only boundary checks, confidence score thresholds, and explicit human confirmation envelopes for proposed transactions.

---

## 4. Acceptance Gate Requirements for v1.0 Release

1. **Zero High/Critical Vulnerabilities**: Bandit, Pip-Audit, and CodeQL pass with zero unresolved alerts.
2. **100% Deterministic Financial Arithmetic**: Zero use of floating-point numbers in money, tax, and inventory quantity pipelines.
3. **Restoration & Recovery Verification**: 347-table populated database restore drill succeeds with byte-identical verified post-recovery state.
4. **Bilingual WCAG 2.1 AA Compliance**: All web Studio user journeys render flawlessly in English (LTR) and Arabic (RTL) without contrast or accessibility violations.
