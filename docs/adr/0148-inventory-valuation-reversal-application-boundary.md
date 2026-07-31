# ADR 0148: Extract valuation reversal as one application boundary

- **Status**: Accepted
- **Date**: 2026-07-28

## Context

Compensating movement validation, cost-layer restoration, reversed Finance
draft creation, maker-checker approval, audit, and outbox effects remained in a
SQLite-bound Platform service despite a partial row repository.

## Decision

Expose all seven reversal use cases through a typed connection-free Application
port. Keep schema checks, transaction ownership, lineage validation, layer
effects, Finance drafts, and evidence in a SQLite adapter. Retain historical
constructors, constants, summary and repository imports through SQL-free
facades.

## Consequences

Exact minor units, original-document lineage, opposite-movement checks,
optimistic layer mutation, SoD, and atomic evidence remain one adapter contract.
The inventory now has one partial repository and twenty-five neutral Application
services. PostgreSQL reversal parity remains open.

## Rollback

No schema or stored data changed. A compatible adapter can replace SQLite
without data conversion; weakening compensating or atomicity invariants is not
an acceptable rollback.
