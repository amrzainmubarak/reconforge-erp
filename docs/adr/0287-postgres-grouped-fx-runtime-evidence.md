# ADR 0287: Exercise FX-aware grouped matching in the PostgreSQL worker

- **Status:** Accepted (bounded E-336 slice)
- **Date:** 2026-08-03
- **Decision owners:** ReconForge maintainers

## Context

The grouped strategy has an explicit FX/rate-policy contract, while the live
PostgreSQL worker had only exercised same-currency one-to-many and
many-to-many runs. A hosted adapter must prove that exact currency conversion,
target-currency selection, and persisted lineage survive the worker boundary.

## Decision

Extend the grouped-worker runtime test with a third run: two USD left records
(`60 + 40`) and one EUR right record (`200`) under an explicit synthetic
EUR→USD rate of `0.5`, `target_currency: USD`, and `many-to-one` mode. The
worker must persist two deterministic edges, expose USD lineage, and match the
direct strategy decision digest. The existing same-currency cases remain
unchanged.

## Boundary

This is one synthetic fixed-rate PostgreSQL 16 single-node worker cycle. It
does not prove live-market rates, FX governance, accounting treatment, scale,
soak/backpressure, distributed capacity, HA/DR, posting, or write-back.
