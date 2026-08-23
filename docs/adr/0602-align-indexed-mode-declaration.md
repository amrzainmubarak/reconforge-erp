# ADR 0602: Align indexed strategy mode declaration with execution

## Status

Accepted — 2026-08-23

## Decision

The indexed one-to-one strategy manifest explicitly declares `one-to-one` in
its supported modes because the adapter already accepts exactly that request
mode. The architecture manifest and pinned digest are updated together.

## Boundary

This corrects a declaration drift and closes one mode-inventory gap. It does
not claim that all advanced matching families exist or that mode declaration
proves algorithmic correctness.

## Rollback

Any future mode change requires a versioned manifest, regenerated digest, and
runtime/architecture contract tests in the same change.
