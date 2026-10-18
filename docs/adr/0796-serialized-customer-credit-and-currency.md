# ADR 0796: Serialize receivables against one customer credit profile

Date: 2026-10-03. Status: accepted. Scope: PROD-007.

Customer currency edits could reinterpret existing history; approval could accept
an inactive customer, and concurrent SQLite approvals exceeded the credit limit.
Freeze customer currency after any invoice or receipt, including draft/cancelled
history. Preserve same-currency metadata edits and pre-history currency changes.
Require Active status and a matching currency before any credit override check.
Fail closed when historical invoice/receipt currencies disagree with the customer.

SQLite takes BEGIN IMMEDIATE before mutable reads. PostgreSQL uses a common
customer FOR NO KEY UPDATE lock for profile updates, document creation, receipts,
allocations, approvals and exposure reads. First creation uses INSERT ON CONFLICT
DO NOTHING, then reads under that lock, handling both deterministic primary-key
and business-key conflicts. Preserve existing maker/checker, version checks,
idempotency surface and transactional audit/outbox semantics.

Verification: before-fix29 failures/three passes; final89 passed, zero skipped,
54.02s with real restricted-role PostgreSQL. Tests race approval/profile/first
creation and inject audit/outbox failure. Ruff, Mypy and Bandit pass. Source
rollback requires an alternative verified credit/currency guard; no historical
amount or document is rewritten. Database-administrator mutation, mixed-currency
aging, AR quantity precision, payload-bound idempotency and GL posting remain
separate work. This change does not claim all receivables invariants complete.
