# ADR 0367: Professional invoice-to-payment control slice

- Status: accepted
- Date: 2026-08-05
- Scope: local-first, non-posting professional-services control

## Decision

Add `professional.invoice-payment` as an experimental runtime module. The
module compares two operator-provided JSON exports: invoices and client
payments. It uses exact `Money`, normalized references, client identity, a
bounded payment-date window from invoice due date, and an explicit tolerance.
Every invoice is resolved to at most one payment. Duplicate candidates,
amount/client/date failures, unmatched invoices, and unapplied payments remain
visible decisions rather than being silently allocated.

The application boundary reads through the shared bounded structured ingress,
records file and parsed-document SHA-256 fingerprints, and writes a closed
schema report whose artifact digest can be replay-verified. The CLI is
`reconforge professional invoice-payment run`.

## Non-goals and rollback

This slice does not recognize revenue, allocate receivables, post journals,
authenticate a billing or payment provider, call a network, persist a server
workflow, or write back to an ERP. Removing the module descriptor, CLI wiring,
pack, fixtures, and files is the rollback; no database migration is introduced.

## Evidence boundary

The evidence is synthetic local JSON/CSV execution and focused tests. It does
not establish live provider connectivity, source authenticity, statutory
accounting treatment, HA/DR, production availability, or measured business
outcomes.
