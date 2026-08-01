# ADR 0100: Close the Phase 1–3 execution contract before claiming completion

- Status: Accepted
- Date: 2026-07-27
- Scope: Phase 1 Platform Foundation, Phase 2 Matching and Evidence 2.0, and Phase 3 Enterprise Product

## Context

The backlog contained Platform and Matching/Evidence tasks but no complete
Phase 3 task set, no single mapping from tasks to the three requested phases,
and no machine-enforced treatment of real pilots or independent security review.
That allowed a future implementation to appear complete by counting only the
tasks already represented in the repository.

## Decision

`docs/execution/PHASE_1_3_EXECUTION_MATRIX.yaml` is the normative closure
contract. Every post-Phase-0 backlog task must appear exactly once in one phase.
Every dependency must exist and may not point to a later phase. Phase closure
requires every mapped task and every required gate to be verified.

Phase 3 includes identity federation, SCIM, service accounts, multi-entity
isolation, scheduling and notifications, administration, connector and signed
pack lifecycles, upgrade/rollback, HA/DR, air-gapped operation, observability,
and a primary-source competitive assessment. Three to five real controlled
pilots and an independent security review are explicit external tasks and gates.
Synthetic rehearsals, repository tests, or maintainer self-review cannot satisfy
those external gates.

## Consequences

- The requested three-phase objective has a finite, inspectable definition.
- CI fails when a new post-baseline task is omitted, duplicated, depends on a
  later phase, or when an external gate is marked verified without artifacts.
- External actors and approved data are ultimately required for complete Phase
  3 closure; they are not inferred from implementation quality.
- Universal superiority, enterprise-readiness, compliance, certification,
  unsupported scale, and unverified customer-validation claims remain forbidden.
- This ADR defines execution and evidence requirements; it does not itself
  implement or complete any technical phase.

## Reversal

Replace the matrix through a reviewed ADR and migrate its contract tests and
backlog atomically. Removing tasks or external gates merely to obtain a passing
status is not a valid rollback.
