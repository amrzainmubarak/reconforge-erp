# ADR 0483: Live PostgreSQL reconciliation HTTP boundary

- **Date:** 2026-08-10
- **Status:** Accepted locally; hosted publication deferred

## Context

The PostgreSQL reconciliation repository and mocked route contracts already
covered deterministic run/input persistence, but they did not prove the
authenticated server path that an API consumer uses. A route-level test must
exercise the identity factory, scope authority, forced tenant/workspace RLS,
exact amount serialization, and the public list/detail/input responses.

## Decision

Add an opt-in live contract using a disposable PostgreSQL 16 instance, a
non-superuser `NOBYPASSRLS` application role, a service-account credential,
and an explicit workspace grant. The test submits one synthetic run through
`POST /api/v1/reconciliations/runs`, reads it through the real list/detail/
inputs endpoints, checks that amounts remain strings representing exact
decimal values, and requires workspace and sibling-tenant denial. The
server-boundaries workflow invokes this complete test file explicitly.

The test creates only synthetic rows and removes them with trigger-safe cleanup
after the run. No provider call, posting, write-back, or background worker is
introduced by this boundary.

## Evidence and limits

The focused test passes locally against PostgreSQL 16 with a non-superuser
role. This is one-host synthetic HTTP/RLS evidence. Hosted CI execution,
live bank/ERP interoperability, matching worker completion, distributed
capacity, HA/DR, and production readiness remain separate gates.

## Rollback

Remove the test, workflow invocation, inventory evidence, and this ADR after
confirming that no external consumer relies on the added CI boundary. No
schema downgrade is required.
