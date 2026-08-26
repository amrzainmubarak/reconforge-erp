# ADR 0658: Nonstandard-currency engine parity regression

- **Status:** Accepted
- **Date:** 2026-08-26
- **Decision owners:** ReconForge execution slice

## Context

The existing matching parity properties protect deterministic results for
generic and USD-shaped synthetic records. That coverage does not by itself
prove that currency policies with zero or three minor units remain stable when
data is serialized, read by different engines, hashed, and processed through a
partitioned execution path.

## Decision

Add a deterministic regression that generates JPY and KWD datasets, asserts the
resolved manifest currency policy, and compares the complete engine result
contract across:

1. Pandas execution;
2. DuckDB full-scan execution; and
3. DuckDB execution with the partition threshold deliberately forced.

The contract includes the reconciliation signature, policy/version metadata,
record counts, and summary counts. Equality is required across all three modes
for each currency.

## Consequences

This creates a durable local regression for two materially different currency
precision policies and for a partition boundary. It is test-only and preserves
all runtime compatibility. It does not establish universal currency coverage,
all supported engine versions, live providers or FX rates, capacity/soak,
posting/write-back, HA/DR, or production readiness.

## Rollback

Revert the E-964 test and its execution documentation. No schema, data, or
external state changes are involved.
