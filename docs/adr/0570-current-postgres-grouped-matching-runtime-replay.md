# ADR 0570: Current PostgreSQL grouped matching runtime replay evidence

## Status

Accepted — 2026-08-23

## Context

The grouped strategy and PostgreSQL worker adapter already had persistence-free
parity contracts. A current runtime gate is needed to show that the same
lineage, tenant boundary, and checkpoint/crash-resume behavior pass through a
real PostgreSQL service under a least-privileged role.

## Decision

Record the current local runtime result as bounded evidence only. The gate uses
PostgreSQL 16.14 image digest
`sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777`,
the `reconforge_app` role with `rolsuper=false` and `rolbypassrls=false`, and
the existing grouped runtime/application test files. Secrets are not retained
in evidence.

## Evidence

The grouped runtime/application file passed 8/8 with no skips, including
tenant-scoped persistence, grouped lineage, and process-crash resume without
duplicate partitions. The run used synthetic data and one local Docker host.

## Limits

This does not prove PostgreSQL HA/DR, cross-host recovery, hosted CI, provider
interoperability, capacity/soak, production SLOs, or regulated readiness.
