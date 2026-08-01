# ADR 0168: Live PostgreSQL Phase 1 remediation gate

## Status

Accepted — 2026-07-28

## Context

All Application boundaries had PostgreSQL adapters and optional live tests, but
availability was not current runtime evidence. A fresh PostgreSQL 17.10 service
exposed migration, row-shape, query-schema, ordering, and trigger defects that
static and skipped tests could not reveal.

## Decision

Define E-163 as one disposable, synthetic, non-superuser live gate. It upgrades
a fresh database through Alembic 0033, runs every test named by the parity
inventory, exercises downgrade to 0011 and re-upgrade in a separate database,
and runs the encrypted native backup/isolated-restore/cleanup contract. CI must
derive its Application test list from the inventory and pin its PostgreSQL
service image by digest.

Use one immutable hybrid psycopg row factory at the connection factory so old
positional adapters and new mapping adapters share a deterministic boundary.
Migration SQL executes through SQLAlchemy text handling; revision identifiers
remain within Alembic's 32-character storage contract. Database ordering fields
must encode business sequence rather than rely on transaction timestamps.

## Consequences

The current Team single-node PostgreSQL boundary is live-verified with synthetic
data, including encrypted backup and isolated restore. This closes
P1-PLAT-002 for the declared supported Application boundaries. It does not
prove HA, host-loss recovery, managed keys, production RPO/RTO, regulated
deployment, production readiness, or external assurance; P1-PLAT-010 and later
deployment tasks retain those gates.
