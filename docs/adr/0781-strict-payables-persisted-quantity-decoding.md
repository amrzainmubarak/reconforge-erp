# ADR 0781: Strict persisted Payables quantity decoding

- Status: Accepted
- Date: 2026-08-29
- Owners: Financial Integrity / Payables

## Context

Payables quantity ingress already rejects binary floating-point and
scientific-notation inputs. The SQLite and PostgreSQL three-way-match paths
still decoded persisted ordered, invoiced, and received quantities with
direct `Decimal(str(...))` conversion. That left arithmetic dependent on a
weaker boundary if a database row or adapter returned malformed, non-finite,
negative, or otherwise non-canonical quantity data.

## Decision

Use an adapter-local `_stored_quantity()` decoder for every persisted quantity
that participates in receipt limits or three-way matching. The decoder uses
`parse_exact_amount()` and fails closed on invalid or negative values; zero is
allowed only for an empty receipt aggregate. PostgreSQL reads the canonical
`received_quantity_text` shadow values and sums them after decoding, keeping
the arithmetic tied to the exact persisted representation.

## Consequences and rollback

Malformed or tampered quantity data cannot silently enter receipt-limit or
three-way-match arithmetic. Valid arbitrary-scale quantities retain their
exact values, and no schema or migration change is required. Rollback is a
source/test/ADR/execution-record revert with no external-state mutation.

This is persisted quantity-integrity evidence for the bounded Payables
workflow. It does not claim complete inventory-unit semantics, source
authenticity, statutory posting, settlement, or production assurance.
