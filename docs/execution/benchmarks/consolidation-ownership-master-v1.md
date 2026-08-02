# Consolidation ownership master v1

Date: 2026-08-02 (Africa/Cairo)

Migration 26 introduces `consolidation_ownership_interests`, an immutable
SQLite master for approved direct ownership revisions. The application port
accepts the existing typed `ConsolidationOwnershipInterest` domain object and
persists exact Decimal text, source digest, effective interval, and approval
lineage under workspace/group scope.

The adapter rejects a second overlapping interval for one subsidiary, requires
the authenticated actor to be the preparer, and refuses self-approval through
the domain invariant. `resolve_effective` reconstructs and validates domain
objects, then returns exactly one active interest per subsidiary for a reporting
date. Direct SQL update and delete are rejected by immutable triggers.

Backup and restore include the new table and replay the effective master before
close lifecycle rows. Focused evidence: 23/23 consolidation tests passed,
including migration, overlap, isolation, tamper, and restore contracts.

This is local SQLite evidence only. PostgreSQL parity, acquisition/fair-value/
goodwill/equity-method policy, ownership-change accounting, statutory
statements, and API/CLI/UI exposure remain outside this slice.
