# ADR-0300: PostgreSQL grouped matching bounded scale profile

- Status: Accepted for a bounded experimental evidence slice
- Date: 2026-08-03
- Scope: PostgreSQL reconciliation worker and grouped matching adapter

## Decision

Add a reproducible, synthetic PostgreSQL profile that drains 32 reconciliation
runs, two hard-key partitions per run (64 partitions total), with four
independent worker connections. The profile cycles through one-to-many,
many-to-one, true many-to-many, portfolio partial-settlement, and explicit
EUR-to-USD FX-aware grouped modes. Each input declares the bounded source-use
count required by the per-source projection of grouped edges.

The acceptance contract requires all runs and partitions to complete, the
expected deterministic result-row count, no duplicate result identities, no
failed or active runs, per-mode completion counts, and non-empty effect and
manifest digests. Decimal values are canonicalized before persistence so
PostgreSQL `Decimal` scale such as `0E-18` cannot become an invalid financial
lexeme.

## Why

Single-run PostgreSQL evidence already covered grouped worker lineage,
many-to-many, FX, portfolio, and crash/resume behavior. The missing bounded
runtime question was whether those same partitions could be drained by
multiple independent workers while preserving checkpoints and result
identity. This profile closes that narrow evidence gap without implying a
capacity or service-level target.

## Rejected claims

This ADR does not establish throughput, soak behavior, production sizing,
large-domain performance, cross-host scheduling, queue HA, automatic failover,
RPO/RTO, statutory posting, live market rates, or ERP/bank interoperability.
The workload is synthetic, one-tenant, single-node PostgreSQL 16 runtime
evidence with an injected local environment.

## Rollback

The benchmark and its tests/docs are additive. Removing the profile files and
their manifest entries reverts this evidence slice; no migration, API, schema,
or persisted production contract is changed.
