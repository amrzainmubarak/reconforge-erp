# Current-State Architecture Snapshot

## Boundary map (implemented today)

- `reconforge/reconciliation/`: transactional reconciliation logic for stock-GL and work-order checks.
- `reconforge/rules/`: configurable control/rule execution and evaluation.
- `reconforge/reports/`: report rendering and artifact writing.
- `reconforge/evidence/`: evidence case modeling, binder generation, and manifest output.
- `reconforge/platform/`: workflow services and local match APIs backed by SQLite.
- `reconforge/auth/`, `reconforge/audit/`, `reconforge/workflow/`: operational metadata and transitions.
- `reconforge/api/` and `reconforge/studio/`: service and UI surfaces.
- `reconforge/engines/`: engine façade used for execution mode comparison.

## Current strengths

- Deterministic stock-to-GL matching already uses an optimization pass rather than a simple greedy pass.
- Data-quality exceptions are surfaced into explicit frames for reporting.
- Review state and evidence generation are integrated.

## Current gaps versus objective

- Determinism and one-to-many/many-to-many matching behavior are converging, but policy coverage is still incomplete for full financial modules.
- Empty aggregation paths in some workflows are not yet hardened.
- Decimal-backed monetary guarantees are still inconsistent across all matching engines.
- Persistence abstraction for hosted and tenant-safe operation is present in fragments and not consistently normalized across all modules.

## Platform matching status (implemented this pass)

- Platform matching now uses indexed candidate generation with min-cost assignment.
- Reference normalization is applied for matching keys with stable normalized and raw value preservation in explanations.
- One-to-many, many-to-one, and many-to-many behavior are policy-controlled in platform matching.
- Deterministic matching regressions were added for row shuffles and explicit identifier fallback cases.

## Risk posture by component

- Reconciliation: moderate, with explicit parsing and exception handling but uneven global matching approach.
- Controls/rules: stable, but rule explainability for new exception categories needs consistent schema extension.
- Evidence: functional, but resilient behavior for empty inputs needs hardening.
- API and UI: usable, with gaps in versioning and stability commitments under advanced scale modes.
