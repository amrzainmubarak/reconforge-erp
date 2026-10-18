# ADR 0772: Add a strict canonical-money replay reader

- Status: Accepted
- Date: 2026-08-29
- Owners: Financial Integrity / Domain Foundations / QA

## Context

`Money.from_canonical_dict()` validates the embedded currency policy and
registry provenance, but it is also a compatibility reader. Currency lookup
and exact-precision restoration may normalize accepted input before returning
the typed value. That is useful for compatible readers, but persisted
financial evidence and replay verifiers need a stronger guarantee: the
supplied mapping must be exactly the deterministic serialization emitted by
the producer.

The acquisition bridge, PPA, deferred-tax, and ownership-change replay paths
had begun to enforce this rule independently. Duplicating the comparison in
each domain verifier risks inconsistent boundaries and makes future replay
paths easy to implement incorrectly.

## Decision

Add `Money.from_strict_canonical_dict()` as an additive API. It first applies
the existing policy, registry, precision, and schema checks, then compares the
original mapping with `to_canonical_dict()` and fails closed if any field was
normalized or changed. Existing `from_canonical_dict()` behavior remains
unchanged for compatibility readers.

Use the strict reader in non-posting financial replay verifiers for the
acquisition bridge, acquisition PPA, acquisition deferred tax, and ownership
change artifacts. A re-signed payload with padded/scientific amount text,
lowercase currency, altered provenance fields, or any other non-canonical
mapping is rejected before balance or derived arithmetic is accepted.

## Consequences and rollback

Canonical producer artifacts remain compatible, while replay verifiers now
share one tested serialization boundary. Compatibility callers can continue
using the existing reader and are not silently tightened by this change.
Rollback is an additive API/use-site/test/metadata revert; it does not modify
financial data, schema versions, or deployment state.
