# ADR 0563: Consolidate deployment-mode evidence without inferring readiness

- Status: Accepted
- Date: 2026-08-23
- Decision owners: Deployment Governance / SRE / Security

## Context

ReconForge already has separate evidence-bounded audits for upgrades,
PostgreSQL recovery, sovereign installation, observability, and governance.
Those artifacts were not joined into one mode-specific view, making it easy to
mistake a strong local drill for a complete Community, Team, Enterprise, or
Regulated deployment claim.

## Decision

Maintain `docs/execution/DEPLOYMENT_READINESS_MATRIX.v1.yaml` as a closed,
schema-validated matrix. Each edition lists the same eight required gates,
links only to repository-visible evidence, records `verified_scoped`, `partial`,
or `open`, and provides a boundary sentence. The matrix permits only `partial`
or `open` edition status; it cannot express a generic `ready` or `verified`
mode. A regression test validates schema closure, all four editions, gate
coverage, and evidence-path existence.

## Consequences

- Operators get one review surface for mode-specific gaps and evidence links.
- Existing scoped audits remain authoritative; the matrix does not duplicate
  their runtime assertions or upgrade their maturity.
- Regulated key custody, independent failure domains, external IAM, and
  production readiness remain explicitly open where evidence is absent.
