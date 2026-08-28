# ADR 0553: Bind deferred-tax preparation to amount-bounded ABAC

- **Status:** Accepted
- **Date:** 2026-08-23
- **Execution slice:** E-839

## Decision

The deferred-tax prepare route converts its canonical items to typed domain
Money before policy. It passes the gross absolute sum of `fair_value` amounts to
server-scoped ABAC before PostgreSQL persistence. `tax_basis` is intentionally
not added a second time: it is the comparison side of the same tax-base item,
not a second exposure. Existing domain validation remains authoritative for
currency and precision; read-only retrieval remains amount-free.

This is one bounded route proof, not universal financial-route or production
IAM evidence.
