# ADR0864: Isolate regression fixtures across local and server profiles

- Status: Accepted
- Date: 2026-10-18

## Context

A full regression with an explicitly configured synthetic PostgreSQL service
reproduced three API test defects. The local TLS CLI test inherited a server
DSN. The legacy AR test assumed that a shared role had never received grants
from another integration test. The service-account test reused tenant IDs,
omitted dependent domain audit rows during cleanup, and expected a local
workflow operation that the server boundary deliberately refuses (ADR0637).

## Decision

Clear only the server DSN in the local TLS test. Give the AR privilege test a
unique, ordinary login with no superuser, bypass-RLS or role/database creation
capabilities; revoke its test-owned grants and remove the login on teardown.
Use unique service-account tenant IDs and the existing child-first cleanup
helper, including its audit ledger dependencies and explicitly named immutable
triggers. The helper checks constraints before restoring triggers, verifies no
scoped rows remain, and rolls back failures. Extend its existing scope and
rollback regression tests to the service-account cleanup plan.

Assert the existing `workflow_server_backend_unavailable` refusal, matching
the test file's non-live service-principal coverage. Do not expose an additional
server workflow backend to satisfy a stale test expectation.

## Compatibility and rollback

These changes affect test fixtures only. No product financial rule, permission,
SQL guard, migration, API response or default network behavior changes. The
mandatory native gate continues to reject skipped selected tests. Reverting
this test-only change restores the old fixture behavior, including its known
order/environment dependence; there is no production data migration to reverse.

## Fresh migrated-role follow-up

An additional189-case cohort in70 isolated databases reveals42 failures in ten
files: eight fixture cases and34 AR cases lacking their declared role profile.
OIDC needs current assurance/emergency/scope access; a service principal needs
scope reads and policy-audit append privileges. Tenant provisioning for the three
SCIM fixtures belongs to the admin connection. The legacy master fixture needs
read-only financial parent indexes; scheduler callbacks need subscription/route
reads; the outbox verifier needs read-only delivery evidence. Its security-definer
writer remains the only evidence writer.

The eight repaired cases each use `isolated_postgres_runtime_role`, with explicit
finite grants and unchanged FORCE RLS, ownership and DML on read-only dependencies.
All eight pass in49.687s wall without skips and are selected by mandatory CI.
AR fixture provisioning exposes a separate product lock-order defect (ADR0867).
