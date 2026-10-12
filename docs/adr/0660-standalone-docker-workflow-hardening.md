# ADR 0660: Standalone Docker workflow hardening

- **Status:** Accepted
- **Date:** 2026-08-26
- **Decision owners:** ReconForge execution slice

## Context

The dedicated Docker workflow was weaker than the CI and release candidate
paths. It used a default cached build and ran Doctor with a writable output
mount and normal network/capability settings. That weakened the evidence for
the exact workflow most likely to be used as a quick PR/push container check.

## Decision

Make the standalone workflow use:

- `docker build --pull --no-cache --platform linux/amd64`;
- a finite 20-minute job timeout; and
- `docker run` with `--network=none`, `--read-only`, `--cap-drop=ALL`, and
  `--security-opt=no-new-privileges`.

The output volume is removed from the Doctor smoke because this check is an
inspection-only runtime assertion and does not need writable host storage.

## Consequences

Recurring Docker PR/push evidence now matches the bounded hardening contract
used by CI and release candidates. The workflow remains a single-host CI
check. It does not establish hosted clean-build identity, signed provenance,
vulnerability reachability or disposition, registry publication, cross-host
behavior, or production deployment assurance.

## Rollback

Revert the workflow flags, regression test, ADR, and E-966 execution entries.
No application or data migration rollback is required.
