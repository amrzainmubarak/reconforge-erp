# ADR 0591: Gate the Python base-image upgrade behind compatibility evidence

## Status

Accepted — 2026-08-23

## Context

Docker Scout recommendations for the current local image identify the pinned
`python:3.11-alpine` line as current and suggest `3.12-alpine` as a smaller
alternative with fewer packages and fewer reported vulnerabilities. The
project's supported CI matrix and current Dockerfile are still centered on
Python 3.11, so changing the runtime solely from a scanner recommendation could
introduce compatibility or packaging drift.

## Decision

Keep the current digest-pinned Python 3.11 Alpine base for this slice. Track a
Python 3.12 Alpine upgrade as planned work requiring, at minimum:

- refreshed digest and Docker Scout scan;
- full Python 3.11/3.12 regression and engine-parity matrix;
- package/air-gap/install verification;
- Docker doctor/validate/control-pack smoke;
- web/API compatibility and rollback evidence;
- explicit release note and rollback plan.

No base-image change is made from this recommendation alone.

## Boundary

Docker Scout's recommendation is recorded evidence, not a vulnerability or
release approval. Hosted scanner parity and production image policy remain
open.
