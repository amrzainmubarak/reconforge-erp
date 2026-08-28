# ADR 0552: Bind intercompany elimination preparation to amount-bounded ABAC

- **Status:** Accepted
- **Date:** 2026-08-23
- **Execution slice:** E-838

## Context

The intercompany elimination prepare route accepts explicit canonical Money
lines and persists a non-posting proposal. Its server-scope policy check ran
before line conversion and did not receive the financial magnitude constrained
by an amount-bounded grant.

## Decision

Convert every input line to the typed domain contract first, then compute the
gross absolute source amount with Decimal arithmetic and pass it into the
server-scoped policy check before persistence. The absolute sum represents the
gross source exposure without allowing reciprocal positive/negative lines to
cancel the authorization magnitude. Invalid or cross-currency domain input
still fails before policy or persistence.

## Compatibility and limits

The helper amount remains optional and local behavior is unchanged. This proves
one intercompany route with synthetic non-posting data, not every financial
route, live provider behavior, or production IAM effectiveness.
