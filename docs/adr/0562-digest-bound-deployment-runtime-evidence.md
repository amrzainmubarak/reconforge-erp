# ADR 0562: Bind deployment runtime facts to a closed offline evidence manifest

- Status: Accepted
- Date: 2026-08-23
- Decision owners: Deployment Governance / Platform Security

## Context

Deployment edition validation already fails closed when required runtime facts
are absent, but callers had to construct `DeploymentRuntimeFacts` in code.
That is difficult to reproduce and does not create a stable evidence identity
for review or an eventual admission workflow.

## Decision

Introduce a strict JSON-shaped runtime-evidence manifest containing one edition
and the exact runtime facts consumed by `validate_deployment_profile`. The
offline verifier rejects missing or extra fields, wrong types, unsupported
editions, and invalid profile values. It returns deterministic profile findings
and a canonical SHA-256 digest. The CLI command
`reconforge deployment verify-runtime-evidence MANIFEST.json` exposes this
contract without network, secret, database, IAM, or storage probes.

## Consequences

- Operators and CI can reproduce the exact facts and digest used for a profile
  validation decision.
- Findings remain explicit; a clean local manifest is not silently promoted to
  deployment readiness.
- External systems, backup/restore drills, key custody, failure domains, and
  production enforcement still require independent runtime evidence.
