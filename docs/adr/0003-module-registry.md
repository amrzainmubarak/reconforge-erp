# ADR 0003: Read-Only Runtime Module Registry

- Status: Accepted for the module-metadata foundation
- Date: 2026-07-21
- Decision owners: ReconForge maintainers

## Context

ReconForge ships file workflows, DB-backed foundations, export adapters, two Studio surfaces, and a broad documented roadmap. Without a machine-readable boundary, a client or operator could confuse planned ERP breadth with code present in the runtime. A dynamic plugin loader would be premature because installation trust, package signing, permission grants, migration ownership, compatibility, network declarations, and removal semantics are not yet designed.

## Decision

1. Add a static, typed, read-only registry for shipped runtime slices.
2. Separate compatibility maturity (`stable`, `beta`, `experimental`) from capability status (`implemented`, `foundation`).
3. Prohibit `planned` from runtime descriptors. Roadmap-only work remains documentation.
4. Require local-first posture, external-call posture, dependencies, incompatibilities, permissions, migrations, domain events, interfaces, contracts, data classification, retention/activation notes, and bounded test-evidence paths.
5. Validate unique IDs, known references, migration compatibility, and an acyclic dependency graph deterministically.
6. Expose inspection as table or versioned JSON through `reconforge modules`; do not import module code or mutate activation state during inspection.
7. Cross-check declared permissions against a migrated database in the test suite.

## Consequences

### Positive

- Product surfaces can distinguish present capabilities from roadmap claims using one contract.
- Dependency and migration mistakes fail before a future activation layer relies on them.
- Maintainers must link every runtime entry to concrete test evidence and data-handling notes.
- JSON output creates a safe future input for documentation, diagnostics, and permission-aware clients.

### Costs

- Metadata must be updated when interfaces, permissions, migrations, or maturity change.
- The registry describes activation but does not yet enforce it.
- Static descriptors do not provide third-party discovery.

### Deferred work

- Signed third-party package manifests and trusted installation policy.
- Explicit enable/disable persistence and lifecycle hooks.
- Dependency version ranges and compatibility negotiation.
- Module-owned reversible migrations and removal policy.
- Permission grant review and UI route/action derivation.

No deferred item should be represented as implemented merely because a metadata field now exists.
