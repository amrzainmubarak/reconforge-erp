# ADR 0572: Current PostgreSQL write-back history runtime evidence

## Status

Accepted — 2026-08-23

## Context

Write-back governance requires append-only, tenant-scoped, idempotent history
before any provider transport is considered. Existing schema and adapter tests
need a current live PostgreSQL observation under the application role.

## Decision

Record the live `tests/test_postgres_writeback.py` run against PostgreSQL 16.14
image digest
`sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777`
using `reconforge_app` with `rolsuper=false` and `rolbypassrls=false`. Keep the
provider-neutral boundary: no secret resolution or network dispatch occurs.

## Evidence and limits

All three tests pass, covering append-only scoped history, idempotent replay,
tamper refusal, and ERPNext payment history replay. This is one local Docker
host with synthetic data; it does not prove live-provider behavior, HA/DR,
cross-host recovery, or production write-back readiness.
