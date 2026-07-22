# Product and Engineering Roadmap

## Phase 0 — Baseline and risk control

1. Finish baseline architecture and risk documentation.
2. Identify row-order edge cases and empty-result failure modes.
3. Add invariant and regression tests for deterministic output and empty-frame safety.

## Phase 1 — Financial correctness hardening

1. Eliminate remaining row-order dependence outside stock-GL matching.
2. Formalize stable exception taxonomies and deterministic IDs.
3. Introduce explicit decimal-backed monetary value object for reconciliation and control scoring.
4. Guarantee all valid-empty outputs are typed, non-crashing frames.

## Phase 2 — Matching architecture expansion

1. Promote global optimization options across platform matching services.
2. Add one-to-many and many-to-many modes with explicit policy and risk controls.
3. Add synthetic golden datasets for ambiguity and partial matching.

## Phase 3 — Engine and persistence scale

1. Validate engine parity claims between pandas and duckdb execution.
2. Introduce chunking and resumable job modes for large datasets.
3. Add migration-safe persistence changes for optional hosted/postgres support.

## Phase 4 — API, CLI, and security

1. Versioned API interfaces with audit-safe error handling and idempotent writes.
2. CLI coverage for reconcile, verify, backup, restore, and benchmark workflows.
3. Strong threat-model-driven controls for session/review integrity.

## Phase 5 — Delivery quality

1. Performance regression checks in CI for stable benchmark slices.
2. Update contributor and governance artifacts as scope increases.
3. Publish a release-readiness gate with explicit evidence of implemented claims.
