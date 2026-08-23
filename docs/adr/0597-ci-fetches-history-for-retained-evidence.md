# ADR 0597: Fetch complete history for retained evidence contracts

## Status

Accepted — 2026-08-23

## Decision

The required Python `test` matrix job uses `actions/checkout` with
`fetch-depth: 0`. Several retained, digest-bound evidence artifacts refer to
the exact migration/source commits that produced them; the test contract must
be able to verify those commits in hosted CI as well as in a full local clone.

## Boundary

This improves evidence verification and does not trust history alone: tests
still compare source digests, report digests, and schema contracts. It adds
checkout time and does not prove hosted provenance or release approval.

## Rollback

Reverting to a shallow checkout is not allowed while retained evidence tests
require historical commit verification. Removing those artifact contracts
would require a separate ADR and migration.
