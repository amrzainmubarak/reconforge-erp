# ADR 0650: Enforce parent-period lock on consolidation run transitions

## Status

Accepted — 2026-08-26

## Context

The local consolidation adapter already refused run transitions after a parent
period was locked. The PostgreSQL adapter locked only the run row, so a
posted-run reversal could proceed after the period lock.

## Decision

For every PostgreSQL consolidation run transition, resolve the parent period,
lock it with `FOR UPDATE`, reject `Locked`, then re-read and lock the run
before evaluating its expected state and applying the transition. This matches
the SQLite lifecycle and keeps approval, posting, and reversal within the
non-posting ReconForge control-journal boundary.

## Boundary and rollback

This is adapter-level period governance. It does not implement statutory or
legal-book posting, source-ERP locking/write-back, distributed locking, HA/DR,
or production assurance. Rollback is a code revert; no schema migration is
required.
