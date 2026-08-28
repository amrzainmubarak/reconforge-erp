# ADR 0604: Require permutation replay for fee and FX matching

## Status

Accepted — 2026-08-23

## Decision

The bounded one-to-one fee/FX contract includes a replay test that reverses
caller-supplied FX-rate order and requires identical input and decision
digests, results, and explanations. Canonicalization must make equivalent
rate definitions order-independent.

## Boundary

This proves local permutation invariance for the tested synthetic case. It does
not prove cross-engine parity, rate-source authenticity, market valuation, or
production throughput.

## Rollback

Any relaxation requires a versioned digest contract and an explicit migration;
order-dependent financial decisions are not an acceptable fallback.
