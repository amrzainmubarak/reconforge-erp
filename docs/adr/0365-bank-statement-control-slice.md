# ADR 0365: Add an export-based bank statement control slice

- **Date:** 2026-08-05
- **Status:** Accepted for the experimental Phase 4 breadth track

## Decision

Add a bounded `bank.cash-reconciliation` module that compares a local CAMT.053
statement with a local JSON ledger export. The module uses exact `Money`,
normalized references, one-currency policy, amount tolerance, booking-date
window, deterministic candidate ordering, explicit ambiguity/exception/unmatched
statuses, source fingerprints, and a digest-bound report.

The first interface is a non-posting CLI/library slice. It does not authenticate
bank origin, connect to a provider, initiate payments, post journals, write back
to an ERP, or persist state outside operator-selected local files.

## Rationale

This delivers a useful professional and banking-adjacent control while keeping
the source-system boundary explicit. CAMT.053 parsing remains in the existing
connector boundary; this module consumes its typed result rather than creating a
second parser or a hidden provider integration.

## Verification and rollback

The slice is covered by `tests/test_bank_statement_control.py`, the module
registry/threat-model parity tests, the declarative pack, and the full local
regression/static/package gates recorded as E-437/E-438. Rollback is removal of
the module, CLI wiring, fixtures, pack, schema, docs, registry entry, and tests
in one reviewed commit; existing CAMT.053 ingestion is independent.

## Explicit non-goals

Live bank/ERP connectors, payment initiation, fraud detection, statutory posting,
write-back, persistence/API/Studio, HA/DR, provider interoperability, and
production availability remain separate gates requiring their own evidence.
