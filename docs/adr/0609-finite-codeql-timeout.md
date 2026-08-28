# ADR 0609: Bound the CodeQL analysis job

## Status

Accepted — 2026-08-23

## Decision

The CodeQL `analyze` job has a 30-minute workflow timeout, enforced by a local
workflow contract test. A timed-out analysis remains a failed security gate;
the bound only prevents indefinite runner consumption.

## Boundary

This governs job liveness and does not weaken CodeQL findings, prove absence of
vulnerabilities, or replace independent security review.

## Rollback

Changing the bound requires measured analysis-duration evidence and a contract
test update; removing the bound is not an acceptable rollback.
