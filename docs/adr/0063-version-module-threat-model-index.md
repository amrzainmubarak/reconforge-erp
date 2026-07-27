# ADR 0063: Version the Active-Module Threat-Model Index

- Status: Accepted
- Date: 2026-07-25
- Scope: active module assets, actors, trust boundaries, threat cases, controls, tests, ownership, assumptions, and residual limitations

## Context

The repository had a useful prose threat model and a schema-validated Security
Architecture v2, but neither enforced threat coverage for each active runtime
module. A new module could add an interface, permission, data class, network
dependency, or persistent store without naming its assets, actors, threats,
controls, tests, and accountable owner. Prose could also drift from module
maturity and capability metadata.

P0-SEC-002 requires every active module to link those fields. The index must
reuse the architecture and normalized risk sources rather than create parallel
control or risk ratings. It cannot imply deployment effectiveness, compliance,
certification, penetration testing, or production readiness.

## Decision

1. Make `docs/security/threat-model-index.v1.yaml` the normative module threat
   source and keep `docs/security/threat-model.md` as its readable view.
2. Validate the index with a closed Draft 2020-12 JSON Schema. The top-level
   actor/threat catalogs and each module/asset/threat-case record reject unknown
   fields and unsafe repository paths.
3. Require exact parity with every descriptor returned by the runtime module
   registry, including module ID, maturity, capability status, interfaces, data
   classifications, and at least the descriptor's declared test evidence.
4. Require every module to declare a Security Architecture owner, trust
   boundaries, classified assets, actors, at least two distinct threat cases,
   module tests, assumptions, and out-of-scope capabilities.
5. Require each threat case to reference one shared threat, one or more
   Security Architecture controls, existing tests, zero or more exact normalized
   risk IDs, and explicit limitations. An empty risk link means no exact
   normalized entry; it never means zero risk.
6. Limit threat-case status to `bounded`, `partial`, `deployment-dependent`, or
   `planned`. Every module must retain at least one non-bounded status and the
   module model itself remains `evidence-bounded`.
7. Treat the workspace operator as a scoped deployment dependency, not an
   infallible actor. Authentication is similarly limited and cannot imply
   object, tenant, amount, period, or approval authorization.
8. Review at least every 90 days and on module/interface/network/storage/actor/
   permission/data-class/control/risk/evidence change, incident, vulnerability,
   failed isolation test, or relevant external assessment.
9. Keep current-official-standard mapping, DAST/fuzzing, incident exercises,
   deployment control operation, and independent validation in their separate
   backlog slices.

## Consequences

- A registered module without threat evidence, or a stale interface/data-class/
  test declaration, now fails repository contracts.
- Actor, trust-boundary, data-class, threat, control, owner, and risk references
  are closed, while every evidence path must exist.
- Nine Experimental modules are covered by eight shared threats, with module-
  specific assets, attack surfaces, tests, and limitations. This is traceable
  design evidence, not proof that all threats are mitigated.
- Adding or materially changing a module now carries an explicit threat-model
  maintenance cost in the same review slice.
- P0-SEC-002 can close. P0-SEC-003 and later security-program work remain open.

## Rollback

Retain schema-v1 and its readable view if a successor is introduced. A
successor must version its schema and document migration. Do not return to
prose-only module coverage, delete residual limitations, invent risk ratings,
or preserve a module in the runtime registry without a matching threat entry.
