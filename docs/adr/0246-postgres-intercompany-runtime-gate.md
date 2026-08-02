# ADR 0246: PostgreSQL intercompany runtime gate is bounded

- **Status:** Accepted
- **Date:** 2026-08-02

## Decision

Promote the existing PostgreSQL intercompany adapter through the unskipped CI
server-boundary test. The gate covers exact Decimal import, tolerance matching,
imbalance exception creation, settlement evidence/outbox effects, tenant RLS
isolation, and semantic SQLite parity using synthetic transactions.

## Boundary

This proves an intercompany control workflow, not statutory consolidation,
elimination posting, acquisition accounting, live ERP write-back, HA/DR, or
production scale.
