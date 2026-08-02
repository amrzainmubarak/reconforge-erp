# ADR-0233: Persist effective-dated consolidation ownership masters

- Status: accepted
- Date: 2026-08-02

## Context

The consolidation worksheet already validates ownership in memory, but close
replay could not source approved ownership history from a durable master. A
durable record must preserve exact percentages, source lineage, effective dates,
and maker/checker attribution without allowing silent edits.

## Decision

Add SQLite migration 26 with an immutable `consolidation_ownership_interests`
table. Expose it through a backend-neutral application protocol and a local
adapter that accepts `ConsolidationOwnershipInterest`. Enforce distinct
preparer/approver actors, workspace/group scope, non-overlapping intervals per
subsidiary, deterministic reporting-date resolution, and immutable update/delete
triggers. Include the table in backup and authorized restore replay.

## Evidence and limits

Migration, repository, application, and backup tests pass 23/23. This closes
only durable local ownership master data. It does not claim PostgreSQL parity,
acquisition accounting, ownership-change postings, statutory statements,
external integrations, or UI/API/CLI exposure.
