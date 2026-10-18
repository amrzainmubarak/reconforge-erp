# ADR 0767: Move the bounded runtime base to Python 3.12 Alpine

- **Status**: Accepted for the local candidate runtime
- **Date**: 2026-08-28
- **Scope**: Docker runtime candidate only; hosted publication remains separately gated

## Context

The Dockerfile was pinned to Python 3.11 Alpine while the project lock and
application test matrix already supported Python 3.12. The upgrade must not be
accepted from a tag or version string alone: the exact base digest, runtime
behavior, application matrix, package path, rollback path, and security scan
must be evidenced on the same source revision.

## Decision

Use the official multi-architecture Python 3.12 Alpine index digest
`sha256:d09d15e60962ca365d1cd544a48773bac9d33f2fb1b00f2aa0deec78ade7dc31`
for both Docker stages. The Dockerfile installs the locked runtime with
`uv sync --locked --no-dev --no-editable --python 3.12 --link-mode copy` and
removes build tooling and global pip from the runtime image. The previous
Python 3.11 digest remains the documented rollback target.

## Evidence

- `docker build --pull --no-cache --platform linux/amd64 -t reconforge:python312-candidate .` passed; candidate image digest is
  `sha256:a96d87d994852b9fc7b9f647977413e37f5959a95f0e7d36bc66584a8b529e52`.
- The candidate contains CPython 3.12.14 and imports ReconForge from the
  non-editable runtime environment.
- Hardened networkless, read-only, capability-dropped `reconforge doctor`,
  sample validation, and demo generation all passed. The sample data retains
  ten intentional warnings and zero errors.
- Docker Scout 1.24.0 scanned the candidate subject on linux/amd64: 82
  packages, zero Critical/High/Medium/Low findings, exit 0.
- Full locked all-extra pytest runs passed independently on Python 3.11 and
  Python 3.12. Web `npm ci`, typecheck, 75 tests, and production build passed.
- Package build, air-gap/rollback drills, API boundary tests, and engine parity
  tests passed. The prior `reconforge:current` image ran Python 3.11.16 and
  `reconforge doctor` successfully as the rollback smoke.

## Rollback

Rollback restores the prior Dockerfile base reference
`python:3.11-alpine@sha256:6857d2dae63e052057f2db389a7061188ac9a92a3fa8d402bde68f36df6fada1`
and the matching `--python 3.11` dependency command, then rebuilds and reruns
the hardened Doctor and release gates. At source level, revert this ADR's
implementation commit as one unit; no database migration or persisted data
rewrite is required. The prior image smoke was executed before accepting this
candidate.

## Boundaries

This decision closes the local Python 3.12 Docker candidate gate only. It does
not prove hosted OCI reproducibility, registry publication, signed provenance,
license legal compatibility, cross-platform musl behavior, independent failure
domains, production SLOs, or regulatory compliance. The exact release-integrated
Syft/Grype gate remains subject to a fresh valid Grype database and the hosted
clean-build gate remains open.
