# ADR 0062: Version the Evidence-Bounded Security Architecture Registry

- Status: Accepted
- Date: 2026-07-25
- Scope: trust boundaries, deployment editions, data classification, control ownership/evidence, and residual-risk linkage

## Context

The prior security architecture was a readable baseline with useful controls
and limitations, but it did not provide a closed contract. Trust boundaries,
Community/Team/Regulated modes, data classes, control owners, code/test evidence,
and the governed risk register could drift independently. Presence of a
security statement could therefore be mistaken for implemented control
evidence.

P0-SEC-001 requires a Security Architecture v2 whose implemented claims map to
repository evidence while preserving conservative product and deployment
boundaries. Standards/compliance mapping, module-specific threat models,
release provenance, and penetration testing are separate backlog items and must
not be manufactured by this architecture document.

## Decision

1. Make `docs/security/security-architecture.v2.yaml` the normative versioned
   registry and retain `security-architecture.md` as its readable explanation.
2. Validate the registry with a closed Draft 2020-12 JSON Schema and executable
   contracts. IDs and references between owners, modes, data classes, trust
   boundaries, controls, and residual risks must be unique and closed.
3. Model three explicit deployment modes: bounded Community Local, experimental
   Team/Server, and planned-only Regulated. The presence of optional
   PostgreSQL, Redis, or S3-compatible adapters cannot promote the whole product
   or imply integrated hosted isolation.
4. Define six handling classes: explicitly public synthetic, internal
   configuration, financial sensitive, identity restricted, security/audit
   sensitive, and secret. Generated/redacted data is not public by default; the
   workspace data owner retains classification, retention, and disclosure
   responsibility.
5. Define seven trust boundaries covering file ingress, browser/API ingress,
   local storage, tenant server persistence, optional network dependencies,
   artifact disclosure, and source/build/release. Every boundary must reference
   concrete code and test paths.
6. Define ten bounded or partial controls. `implemented-bounded` still requires
   an explicit limitation; partial controls cannot be described as complete.
   Owners are accountable roles, not claims about staffed operational teams.
7. Link architecture residual risks to the normalized risk register. Tests must
   reject owner or residual-rating drift and require all security, identity,
   privacy, audit, and operations risks to appear in the architecture mapping.
8. Keep standards mapping, module threat-model indexing, air-gap, KMS/WORM,
   HA/DR, independent testing, signing/provenance, and compliance conclusions
   outside this slice. The registry claim boundary forbids inferring them.

## Consequences

- Security architecture claims now fail tests when evidence files disappear,
  references dangle, a risk owner/rating drifts, or Regulated mode is relabeled
  as implemented.
- Optional server and object-storage code is represented without contradicting
  the local-first core or claiming complete hosted isolation.
- Control evidence proves repository presence and bounded tests, not control
  operating effectiveness in a deployment.
- The registry adds maintenance cost: any new network/storage/identity/sharing/
  release boundary must update the model and tests in the same slice.
- P0-SEC-001 can close. P0-SEC-002 through P0-SEC-010 remain independent work;
  this ADR does not satisfy their exit evidence.

## Rollback

Retain schema-v2 registry and its readable boundary even if a later model is
introduced. A successor must use a new schema version and compatibility reader
or documented migration. Do not roll back to prose-only claims, delete
limitations while keeping control labels, relabel planned Regulated mode, or
override the governed risk register from the architecture mapping.
