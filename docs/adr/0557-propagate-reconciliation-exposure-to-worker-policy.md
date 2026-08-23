# ADR 0557: Propagate reconciliation exposure into worker policy rechecks

- Status: Accepted
- Date: 2026-08-23
- Scope: PostgreSQL reconciliation API submission and worker claim path

## Context

E-842 bound the API submission to an exact amount, but the durable worker later
rechecked authorization from a service-account context without receiving that
amount. A bounded policy could therefore evaluate a different object at claim
time than at submission time.

## Decision

Persist `policy_amount` as a canonical decimal string in the immutable rule
metadata created by the API. The worker decodes and validates this value and
passes the resulting finite non-negative `Decimal` to both the tenant policy
check and the pre-claim scoped policy check. Missing metadata is represented as
`None`; it is never interpreted as zero. Invalid stored metadata fails the
worker safely before claiming.

## Consequences and evidence

This reuses the existing durable rule contract and requires no schema migration.
Focused API/worker/policy tests pass 32/32 with one live PostgreSQL skip, and
Ruff/Mypy pass. The proof covers direct run claim/recheck, not the initial
tenant-wide discovery query, worker fleet behavior, live PostgreSQL, provider
execution, accounting posting, or production IAM.

Rollback is a source revert; existing runs without metadata retain the previous
amount-unknown compatibility behavior.
