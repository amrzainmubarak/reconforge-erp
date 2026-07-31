# ADR 0156: PostgreSQL Matching Application boundary

- Status: Accepted
- Date: 2026-07-28

## Context

The PostgreSQL reconciliation store and deterministic engine existed, but the
six-method Matching Application port was absent. Runs also lacked an enforced
workspace ownership link, so similarly named tenant workspaces could not be
distinguished at the persistence boundary.

## Decision

Add migration 0023 with a forced-RLS, tenant-qualified run/workspace link and a
complete `PostgresMatchingRepository`. The adapter reads bounded ingress
documents, executes the shared persistence-independent engine, registers every
source input using engine-returned fingerprints and trusted source positions,
persists every result and exception through the existing reconciliation
integrity repository, and completes the run atomically. Workspace identity is
included in the input fingerprint so an idempotency key cannot replay content
across workspaces. Direct `match_records` uses the same engine and PostgreSQL
currency registry; no SQLite schema or adapter is instantiated.

## Consequences

All six signatures match the Application protocol and historical SQLite/API/CLI
contracts remain unchanged. Existing `NUMERIC(38,18)` PostgreSQL amount limits
fail closed before persistence rather than rounding silently. The optional
non-superuser lifecycle/RLS test is skipped without service credentials, so
maturity is `live_test_available`, not current-live. This is not a scale,
production-readiness, or compliance claim.
