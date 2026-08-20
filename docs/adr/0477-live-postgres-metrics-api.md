# ADR 0477: Live PostgreSQL metrics API contract

- **Date**: 2026-08-09
- **Status**: Accepted locally; hosted verification pending deferred publication

## Context

The metrics API was repaired to use the configured PostgreSQL identity factory
and `PostgresTenantBoundary`. Existing tests covered the wrapper with injected
objects, but did not send an authenticated HTTP request through the real
server-profile path. The historical CI failure therefore lacked a direct
route-level regression contract.

## Decision

Add an opt-in live contract that provisions two disposable tenants, the
PostgreSQL identity/service-account/metrics schemas, and a service account with
only `metrics.read`. Exercise both `/api/v1/metrics/dashboard` and
`/api/v1/metrics/lineage` through `TestClient`, assert the tenant-scoped
responses, and reject the same credential when the sibling tenant is selected.
Invoke the complete `tests/test_api_metrics.py` file explicitly in the
`server-boundaries` workflow.

## Evidence

The local PostgreSQL 16.14 non-privileged run passes. Without a configured
DSN, the test is an explicit capability skip. Focused tests, Ruff, YAML
parsing, and `git diff --check` pass.

## Boundary and rollback

This is one-host synthetic HTTP/RLS evidence only. It does not establish
hosted execution, distributed IAM, provider behavior, throughput, HA/DR, or
production SLOs. Remove the test and workflow invocation to roll back; no
schema or API wire change is required.
