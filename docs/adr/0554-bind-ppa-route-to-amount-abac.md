# ADR 0554: Bind PPA preparation to amount-bounded ABAC

- **Status:** Accepted
- **Date:** 2026-08-23
- **Execution slice:** E-840

## Decision

The PPA prepare route converts its canonical request into typed domain Money
before server policy. It passes `abs(consideration) + abs(nci_fair_value)` as the
gross acquisition exposure. Allocation item book/fair values are intentionally
not added again because they decompose that same acquisition exposure rather
than represent a second transaction. Domain currency/precision validation
remains authoritative, and read-only retrieval stays amount-free.

This is a bounded synthetic route proof, not universal financial-route or
production IAM evidence.
