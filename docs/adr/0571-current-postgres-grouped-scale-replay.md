# ADR 0571: Current PostgreSQL grouped 500/10K scale replay

## Status

Accepted — 2026-08-23

## Context

The grouped worker had versioned scale profiles and prior contract evidence.
The current local PostgreSQL service should be exercised against the declared
500 and 10K partition profiles without turning one host's result into a broad
capacity claim.

## Decision

Record two bounded live runs using PostgreSQL 16.14 image digest
`sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777` and
the `reconforge_app` role (`rolsuper=false`, `rolbypassrls=false`). Require the
existing profile assertions for completed partitions/runs, zero failed runs,
zero duplicate result identities, and zero active runs.

## Limits

The evidence is synthetic, single-host, and one PostgreSQL service. It does not
prove throughput sizing, soak behavior, multi-host capacity, HA/DR, provider
I/O, or production SLOs.
