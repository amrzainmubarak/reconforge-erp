# ADR 0805: Resolve Finance authority through canonical workspace identities

Date: 2026-10-03

Status: Accepted for the bounded Finance hierarchy contract

## Context

Preserving transaction GUCs did not isolate Finance records within one workspace.
The generic scope compositor handles identifier columns; Finance stores natural
organization/entity codes. A guarded nonowner role scoped to entity A1 could
read and void A2 and another organization's entries, without changing any GUC.
Raw writes could also attach a line to another chart's account or substitute a
journal's chart. All reproduction data was synthetic and rolled back.

## Decision

Add migration0095 and restrictive policies on the eight Finance tables. Keep
the existing tenant/workspace policies and FORCE RLS. Resolve organization code
through its canonical organization and exact `application_workspace_id`, then
resolve entity code through that organization. Never equate a code with a GUC's
canonical ID or infer a workspace from the first matching name. Explicit IDs
take precedence; ambiguous workspace names fail.

Shared charts/dimensions and their reference metadata remain readable within
the selected canonical workspace. An organization scope with no workspace GUC
still restricts shared metadata to that organization's workspace. Organization-
scoped actors cannot mutate workspace-shared references, and entity scope cannot
mutate organization-wide Finance metadata. Independent write policies protect
INSERT, UPDATE and DELETE; a read predicate alone is insufficient.

Relationship checks bind accounts to charts, journals to workspace/organization,
entries to journal/entity/period, lines to their entry's journal chart, and line
dimensions to a compatible dimension/value pair. Fiscal periods are workspace
objects; verify their exact workspace rather than inventing an entity binding.
Use a composite parent-account constraint to avoid recursive account RLS. Its
NOT VALID state preserves old rows and does not certify historical affinity;
new writes must satisfy it.

Prevent scope laundering through identity relabeling. Freeze canonical identity
fields and Finance reference identity fields; Validated or Voided control entries cannot
return to Draft and their scope cannot move. Draft replacement must remove its
old lines before changing scope. Preserve entry-line parent identity so attached
dimensions cannot move indirectly. This protects scope without relabeling
existing Validated/Voided control entries as a complete posting ledger.

Canonical parent deletion must not orphan or reattribute history. A narrowly
scoped installed trigger checks only existence, with fixed `pg_catalog` search
path, qualified tables and `row_security=off`; it returns no stored data.
Writers lock canonical parents and entries so competing deletion/reparenting
cannot pass a stale check. Refuse unsupported stale-snapshot deletion/reparenting
rather than assuming serial execution. Tenant-wide cascade handling must not
leave surviving history. Runtime users cannot install or replace these triggers.

## Compatibility and rollback

No automatic data attribution or policy backfill occurs. Unresolved legacy
workspace ownership remains available only through the explicit tenant-only
inspection path; narrowed reads and new relationship writes fail closed. Existing
global organization-code uniqueness is preserved. Identity changes previously
accepted by raw DML may now be rejected even for currently unreferenced rows.
Normal descriptive updates remain supported at the appropriate authority level.

The trigger owner must be able to inspect complete reference existence; an owner
subject to FORCE RLS cannot silently receive a filtered history check. Separate
migration administration remains trusted. A policy downgrade restores weaker
authority and requires an operator-controlled security rollback; it is not an
equally isolated deployment. No data deletion or inferred reassignment is a
rollback step.

This does not make the application credential a sandbox against arbitrary GUC
changes, establish every canonical master-data mutation policy, or complete
immutable GL posting. Those boundaries retain separate acceptance gates.

## Verification and references

Actual PostgreSQL16.14 regression passes478 tests with two explicit native-client
prerequisite skips; two final API contract tests also pass. Independent probes
verify both orders of parent/child races with actual lock waits and losing-write
refusal. The direct installer is tested without relying on generic hierarchy
policies. No legacy attribution is invented.

Native populated Finance restore through real PostgreSQL16.14 Docker clients
preserves values, policies, captured currency metadata and legacy NULLs; scoped
denials and a permitted new Draft write pass after restore. Separate native
write-back migration/restore passes on16.14 and17.10;35 retained-report/runner
tests pass. Source hashes and failed attempts remain in
[the evidence report](../execution/POSTGRES_FINANCE_SCOPE_2026-10-03.json).
[The operator contract](../operations/finance-scope-upgrade.md) describes legacy
inspection, trigger ownership and the weaker-authority downgrade boundary.

PostgreSQL combines restrictive policies with AND and separately checks old row
visibility and new row content. FK existence alone does not grant parent access.
The design uses these documented contracts, checked2026-10-03:
[CREATE POLICY](https://www.postgresql.org/docs/16/sql-createpolicy.html) and
[row security](https://www.postgresql.org/docs/16/ddl-rowsecurity.html).
