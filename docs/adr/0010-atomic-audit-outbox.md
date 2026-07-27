# ADR-0010: Atomic Business Mutation, Audit, and Outbox

## Status

Accepted for local platform mutations; rollout in progress.

## Context

An audit helper that opens and commits a separate transaction can leave a business
mutation committed when its audit append fails. That violates traceability and makes
evidence incomplete.

## Decision

Audit appenders are transaction-neutral when the caller already owns a transaction. A
mutation service must:

1. validate business rules;
2. begin the business transaction;
3. modify business records;
4. append the audit event;
5. append the outbox event;
6. commit once;
7. roll back all writes if any step fails.

The local outbox is formal migrations 13-14. Its delivery state machine provides
bounded claim leases, retry/backoff, dead-letter state, and explicit replay through an
injected publisher. External transport and worker orchestration remain deployment
concerns.

## Consequences

- Audit failures are visible transaction failures rather than silent traceability gaps.
- Services must not call `commit()` before `audit()`.
- Existing legacy services require incremental migration and forced-failure tests.
- Event consumers must be idempotent because delivery is at-least-once by design.
- A stale lease may be reclaimed, so publishers must tolerate duplicate delivery.

## Evidence

The pattern is implemented and tested in matching, journal import, Finance Core entry
lifecycle, and Inventory Core movement lifecycle paths. Delivery behavior is tested in
`tests/test_outbox_delivery.py`.
