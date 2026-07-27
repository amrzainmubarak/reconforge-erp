# ADR 0047: Evidence-Bounded Public and Module Maturity

- Status: Accepted
- Date: 2026-07-25
- Scope: Public positioning and runtime module maturity metadata

## Context

The Claims Evidence Matrix caps the product at Alpha/foundation stage and
several capabilities at Experimental. The runtime registry nevertheless labeled
platform core, reconciliation core, and export mapping profiles Beta. That
metadata is observable through the CLI and exceeded the current evidence
ceiling even though the product documentation was conservative. P0-012 requires
public claims and module maturity labels to fail CI when they exceed the matrix.

## Decision

1. Add closed `MATURITY_POLICY.yaml` and schema. The product public ceiling is
   Alpha; every current runtime module ceiling is Experimental and references a
   named Claims Evidence Matrix row.
2. Downgrade the three Beta descriptors to Experimental. Keep Beta/Stable in the
   type/schema for future evidence-backed promotion; do not remove the values
   from the compatibility contract.
3. Require exact coverage of all registered module IDs, deterministic ceiling
   ordering, valid claim references, and actual-maturity rank not above the
   ceiling. A synthetic promotion regression proves the gate rejects a metadata
   change without policy/evidence change.
4. Scan seven designated public publishing surfaces. Each must retain at least
   one stage/boundary phrase and none may contain the policy's unqualified
   prohibited wording (enterprise-ready, bank-grade, certified/compliant scale
   compounds, production-ready, or equivalent superlatives).
5. Keep the claim-boundary guide outside the publishing-surface list because it
   must name forbidden phrases to teach maintainers what not to publish.
6. Include policy and schema in sdist governance evidence, not the runtime wheel.

## Consequences

- P0-012 is complete for the current module registry and named public surfaces.
- `reconforge modules list --maturity beta` now returns no current modules;
  unfiltered module IDs, schemas, capabilities, and runtime behavior are
  unchanged.
- A future promotion requires the evidence matrix and policy ceiling to change
  intentionally with its tests/runtime evidence. Passing this gate is not a
  release-readiness or control-effectiveness claim.
- The surface allowlist must be updated when a new publishing entry point is
  introduced; undisclosed surfaces remain a documentation-governance risk.

## Rollback

Do not restore Beta labels without new evidence and an intentional policy/ADR
update. If the policy format changes, retain module coverage, rank enforcement,
claim references, forbidden-wording checks, and the synthetic promotion
regression before removing this version.
