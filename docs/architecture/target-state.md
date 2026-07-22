# Target Architecture (Working Draft)

## Guiding principles

- Correctness first: deterministic results, explicit invariants, explainable outcomes.
- Local-first operation remains default, with optional hosted/tenant expansion as a future mode.
- Single financial truth model with immutable decision trail.

## Planned module structure

- Domain layer: canonical finance objects, money primitives, and reference normalization policies.
- Application layer: deterministic reconciliation use-cases and control orchestrators.
- Infrastructure layer: ingestion, engine adapters, persistence connectors.
- API layer: versioned `/api/v1` contracts with consistent pagination/filter/sort/search semantics.
- Studio layer: workflow screens with exception queues, controls, and review approvals.

## Matching engine direction

- Keep min-cost assignment as default for one-to-one scenarios.
- Add explicit strategies for:
  - one-to-many and many-to-one where required,
  - many-to-many where explicitly enabled,
  - partial/split/journal aggregation support behind configuration,
  - deterministic tie-breaking via canonical candidate keys and stable sort orders.
- Apply identical candidate construction policy across stock-GL and platform match services.

## Data and audit model

- Immutable event log per user action.
- Evidence package manifest includes file hashes, run metadata, and deterministic artifact lists.
- Explicit migration ledger for rule packs, schemas, and control pack versions.

## Engineering quality goals

- Stable IDs driven by business keys, not row numbers.
- Property-based tests for row-order invariance and cardinality invariants.
- Cross-engine parity tests where multiple execution engines are present.
- Security tests for path handling, uploads, and review authorization boundaries.

## Phase 1 delivery note

- Platform matching now meets row-order invariance goals for common duplicate-free identifier payloads using deterministic candidate generation + min-cost assignment.
- CLI policy now exposes many-to-many matching as `--allow-many-to-many`.
- Reference normalization is now part of matching scoring and candidate retrieval, with explicit explanation outputs.
