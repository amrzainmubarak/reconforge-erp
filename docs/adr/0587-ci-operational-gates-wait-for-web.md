# ADR 0587: CI operational gates wait for the web quality gate

## Status

Accepted — 2026-08-23

## Decision

The Docker parity and live server-boundaries jobs in `.github/workflows/ci.yml`
depend on both the Python `test` job and the `web` job. They cannot report a
successful downstream operational gate when the browser quality gate failed.

Engine parity, object-storage, and independent HA/DR jobs remain parallel
assurance cells because they do not consume the web artifact and have separate
failure boundaries.

## Boundary

This is workflow ordering and status propagation only. It does not turn local
browser tests into hosted release evidence or prove production operations.

## Rollback

Restore the two `needs` declarations to their previous values. No runtime or
schema migration is involved.
