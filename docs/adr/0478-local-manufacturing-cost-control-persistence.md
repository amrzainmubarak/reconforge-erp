# ADR 0478: Local manufacturing cost-control persistence and API boundary

- **Date**: 2026-08-09
- **Status**: Accepted locally; PostgreSQL parity remains a separate slice

## Context

The experimental manufacturing cost-control module already produced a
deterministic, replay-verifiable export report from synthetic production-order,
material-issue, completion, and scrap inputs. It had no durable local evidence
record or authenticated operator retrieval path. Promoting it directly to a
PostgreSQL-backed surface would combine a new bounded context with an unproven
server parity contract.

## Decision

Add migration 38 with an immutable, workspace-scoped SQLite table and a
repository that enforces bounded canonical JSON, decision/artifact digests,
status-count consistency, replay verification, idempotent writes, central
`finance_core.manage` authorization, and audited persistence. Include the table
in local backup/restore. Expose authenticated local create/list/read routes with
`finance_core.read`, `finance_core.validate`, and `finance_core.manage` checks.
Reject PostgreSQL server-profile use with an explicit 501 until a separate
PostgreSQL repository and parity inventory entry are implemented.

## Evidence

Focused persistence/API tests pass for idempotency, workspace isolation,
tamper refusal, migration gating, backup/restore replay, and route
authorization. The route authorization inventory is 256 contracts with digest
`f7bbce7e04945e06be556f96359a101d5a5cdef48db321ac56471a1009c1c649`.
The full local Python regression exits 0 with only declared capability skips;
Ruff, Mypy, Bandit, pip-audit, package build, and diff-check pass locally.

## Boundary and rollback

This establishes local replay-verifiable, non-posting evidence only. It does
not establish PostgreSQL parity, statutory inventory valuation, live ERP/MRP
connectivity, inventory/WIP/GL posting, write-back, HA/DR, or production
readiness. Remove the route, repository, migration, backup entries, tests, and
manifest/documentation entries to roll back; no external service or production
data is modified.
