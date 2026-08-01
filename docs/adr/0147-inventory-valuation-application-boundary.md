# ADR 0147: Extract governed inventory valuation as one application boundary

- **Status**: Accepted
- **Date**: 2026-07-28

## Context

FIFO receipt/issue valuation, exact cost allocation, policy governance, finance
draft creation, maker-checker approval, cost-layer mutation, audit, and outbox
effects were coordinated by a SQLite-bound Platform service. A lower-level
repository existed, but callers could not substitute the complete use-case
boundary without retaining SQLite in the public service.

## Decision

Expose all eleven valuation use cases through a typed, connection-free
Application protocol and delegating service. Keep schema checks, transaction
ownership, exact allocation, persistence, audit, and outbox behavior in a
SQLite infrastructure adapter. Preserve the historical connection constructor,
constants, summary type, repository imports, and dependent reversal connection
seam through SQL-free compatibility facades.

## Consequences

- Integer minor units and scaled quantity text cross the port unchanged.
- FIFO order, half-even allocation, period/policy controls, SoD, balanced
  Finance drafts, rollback, and public response shapes remain executable.
- The boundary inventory has zero direct-SQLite services, two partial inventory
  repositories, eighteen compatibility adapters, and twenty-four neutral
  Application services.
- PostgreSQL valuation parity is not established by this decision.

## Rollback

No schema or persisted data changed. The facade can be redirected to another
contract-compatible adapter without data conversion. Restoring SQLite coupling
or weakening exact financial and atomicity behavior is not an acceptable
rollback.
