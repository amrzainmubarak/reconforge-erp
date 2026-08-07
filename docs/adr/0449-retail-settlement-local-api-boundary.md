# ADR 0449: Expose local retail settlement evidence through a bounded API

## Context

Retail settlement evidence now has an immutable SQLite repository and a local
CLI persistence option, but operators still need an authenticated read and
replay-safe persistence surface for local integrations.

## Decision

Add authenticated local routes under `/api/v1/retail/settlements` for posting a
closed report, listing workspace-scoped rows, and reading one row by its
decision digest. The write route requires `finance_core.manage`; reads require
one of `finance_core.read`, `finance_core.manage`, or `finance_core.validate`.
Every report is revalidated by the repository before persistence, repeated
writes are idempotent, and network dispatch/posting are disabled. PostgreSQL
server mode returns an explicit unsupported response until a PostgreSQL retail
adapter and parity evidence exist; it never falls back to SQLite.

## Evidence and boundary

`tests/test_api_retail_settlement.py` covers authentication, workspace
isolation, idempotent replay, tamper refusal, and not-found behavior. The
startup authorization inventory is updated to 249 routes with a new digest.
This is local API composition evidence only, not live processor/ERP
interoperability, accounting posting, write-back, PostgreSQL parity, HA/DR, or
production retail readiness.
