# ADR 0803: Preserve caller authority inside financial repository savepoints

Date: 2026-10-03

Status: Accepted

## Context

A runtime-guarded nonowner PostgreSQL role reproduced lost child scope after a
successful nested Finance, AR or Inventory operation. The repository invoked
the tenant setter without organization/workspace/entity values. Releasing its
savepoint retained those cleared settings in the outer transaction. Subsequent
queries saw sibling rows, and a wrongly constructed repository switched tenants.

## Decision

At each operation, read all five scope GUCs in one query. Initialize the requested
tenant only when every field is unset. An existing tenant must match the
repository; preserve every narrower field verbatim without executing a setter.
Reject malformed/partial scope, entity without organization, and inconsistent
entity aliases before business SQL. Never cache scope on pooled connections.

Apply this helper to the eight Finance/AR/AP/Inventory/Master Data application
adapters. Keep the explicit administrative setter, schema installers, transaction
ownership and low-level master-data/audit behavior unchanged. Existing RLS still
determines row access; this helper prevents accidental authority widening.

## Verification and limitations

Fourteen focused tests pass with real PostgreSQL and no skips, including all
eight adapters, scope preservation after success/error/retry, sibling denial,
tenant mismatch, rollback of business/audit/outbox effects and clean reuse of
the same backend PID. The actual broad PostgreSQL selection passes462 of463,
with one explicit missing-native-client prerequisite skip. Before/after seven-
case runtime replays and source hashes are retained in
[scope evidence](../execution/POSTGRES_REPOSITORY_SCOPE_2026-10-03.json).

No migration is required. Code rollback restores the demonstrated vulnerability;
retain the guard or restrict affected workflows when recovering. Trusted code
with arbitrary application SQL can still change custom GUCs. This does not solve
code-based Finance organization/entity RLS or SQLite composable commit ownership;
PROD025 and the remaining PROD024 work track those independently.
