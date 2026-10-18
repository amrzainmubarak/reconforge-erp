# ADR 0661: Docker documentation contract synchronization

- **Status:** Accepted
- **Date:** 2026-08-26
- **Decision owners:** ReconForge execution slice

## Context

The standalone Docker workflow had been hardened, but current README and
release/deployment instructions still showed a cached/default-platform build and
a writable/networked smoke. The deployment guide also repeated historical
Compose/dashboard instructions although no Compose file existed on the current
HEAD. This created an operator and claim-boundary mismatch.

## Decision

Synchronize current operator-facing surfaces with the bounded workflow:

- use the pull/no-cache linux/amd64 build;
- use the networkless/read-only capability-dropped Doctor smoke;
- use bounded tmpfs mounts for ephemeral demo smoke; and
- distinguish retained-output runs from hardened ephemeral verification.

State explicitly that no Compose deployment contract is shipped until a
versioned Compose profile and executable smoke evidence exist. Historical
strategy/report records remain historical and are not promoted to current
support claims.

## Consequences

Operators receive commands that match the current CI contract, and tests will
catch future drift in the release-readiness pages. This does not add Compose,
prove hosted clean-build identity, provide signed provenance, or establish
production deployment assurance.

## Rollback

Revert the documentation/test updates, ADR, and E-967 execution entries. No
runtime or data migration rollback is required.
