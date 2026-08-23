# ADR 0551: Bind Finance Core entry creation to amount-bounded ABAC

- **Status:** Accepted
- **Date:** 2026-08-23
- **Execution slice:** E-837

## Context

E-836 bound the consolidation impairment route to an exact amount policy, but the authenticated Finance Core entry creation route still re-evaluated server scope without the monetary effect of the journal entry. A bounded grant could therefore be evaluated without the amount it was intended to constrain.

## Decision

Before either PostgreSQL Finance Core entry adapter path runs, parse every debit and credit as an exact non-negative amount and use the gross debit total as the single non-duplicated entry effect. Pass that `Decimal` total into the server scope policy re-check. Invalid amount syntax or negative values fail with a safe 400 error before adapter access. The local SQLite compatibility path keeps its existing behavior.

## Rationale

Balanced journal entries have equal debit and credit totals; using one side avoids double-counting the financial effect. Parsing both sides before policy also prevents malformed credit data from bypassing the authorization boundary. No float, implicit zero, currency conversion, or rounding is introduced.

## Compatibility and rollback

The server scope helper's amount parameter is optional, so all existing routes remain source-compatible. This is source-only and requires no migration or data rewrite. Rollback is a versioned code rollback.

## Evidence and limits

The server Finance Core route contract test asserts `Decimal("140.00")` reaches policy for a balanced synthetic entry. This proves one entry route and its adapter boundary, not all financial routes or production IAM effectiveness.
