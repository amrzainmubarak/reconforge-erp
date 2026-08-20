# ADR 0308: Run the PostgreSQL HA/DR drill as a hosted runtime gate

- Status: accepted
- Date: 2026-08-04
- Scope: PostgreSQL synchronous-standby backup, failover, failback, and fencing evidence

## Context

ReconForge already had a Docker drill that creates a primary and synchronous
standby, validates encrypted native backup and isolated restore, refuses an
unacknowledged write during a replication partition, fences the old primary,
promotes the standby, rejoins the former primary read-only, and performs a
failback. The drill was only available as a script and retained artifact; the
main CI workflow ran the quorum simulation but not the real PostgreSQL
runtime path.

## Decision

Add a separate `postgres-ha-dr` CI job using the locked Python/server/backup
dependencies. The job runs
`verify_postgres_ha_dr_repeated.py`, which executes the full Docker drill three
times, rejects leaked labelled containers/volumes/networks, and uploads the
schema-validated report as a build artifact.

## Evidence boundary

This gate proves repeated single-host Docker execution with synthetic data and
an operator test key. It does not prove independent failure domains, quorum or
witness orchestration, automatic failover, cross-zone/site loss, managed-key
custody, or production SLOs/RPO/RTO.

## Rollback

Remove the `postgres-ha-dr` workflow job, its contract test, this ADR, and the
manifest entry. The existing application backup adapter and local/previous
profile artifacts remain unchanged.

## Verification

Hosted CI run `30884962171` passed. Job `91914021265` executed all three
repetitions and uploaded the report; the workflow's remaining Python,
server-boundary, parity, object-storage, Docker, Security, and CodeQL jobs also
passed. The result remains bounded to one Docker host and a manual controller.
