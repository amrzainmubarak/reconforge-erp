# ADR-0023: Bounded Accounts Receivable and Credit-Control Slice

- Status: Accepted
- Date: 2026-07-23

## Context

ReconForge had a bounded Accounts Payable workflow but no operational AR
domain. The repository needs a useful customer-to-cash foundation without
claiming a complete ERP subledger or silently inventing GL, tax, payment, or
collections behavior.

## Decision

Migration 20 introduces a local SQLite AR slice with:

- customer master records with explicit currency, payment terms, credit limit,
  and credit hold;
- exact minor-unit sales invoices and canonical decimal quantities;
- Draft → Submitted → Approved lifecycle with separation of duties;
- approval-time credit-limit and credit-hold checks with permissioned,
  reason-required overrides;
- posted receipts, partial/unapplied balances, and deterministic allocations;
- open-item aging and credit-exposure reads;
- deterministic IDs, optimistic row versions, idempotency keys, audit events,
  outbox events, migration support, and backup/restore coverage.

The service and API remain local SQLite-backed, consistent with the existing
bounded AP slice. The module does not create ledger entries, calculate
statutory tax, execute payments, issue credit notes, run dunning, or write back
to source systems.

## Consequences

The product can demonstrate a governed AR workflow and explainable credit
controls while preserving technical honesty. The database schema is additive
and can later be mapped to a server repository. Future posting, tax, payment,
collections, and ERP-integration slices must define their own invariants,
period controls, permissions, and migration boundaries rather than extending
approval into an implicit statutory posting operation.
