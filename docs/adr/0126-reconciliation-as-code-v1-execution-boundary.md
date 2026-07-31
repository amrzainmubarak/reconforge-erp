# ADR 0126: Reconciliation-as-Code v1 declarative execution boundary

- Status: Accepted
- Date: 2026-07-28

## Context

Reconciliation packs need stable validation, review, test, diff, simulation, and
rollback. Treating YAML as executable Python would violate local-first security,
make results provider-dependent, and allow a configuration file to gain financial
authority that is not represented in the review workflow. Conversely, describing a
full validation/normalization simulation before runtime adapters exist would overstate
the implementation.

## Decision

Publish `reconciliation-as-code-v1` as a closed data contract:

- parse only bounded duplicate-safe YAML or JSON;
- reject executable hook keys and preserve financial tolerances as non-negative plain
  decimal strings;
- type sources, declarative rule steps, registered matching strategies, currency/risk/
  workflow policies, evidence requirements, synthetic cases, and expected results;
- require human approval and prohibit autonomous financial approval in the schema;
- compute canonical SHA-256 content manifests and deterministic structural diffs;
- execute embedded fixtures only through registered versioned matching adapters;
- identify the current execution scope as `matching-adapter-only-v1`;
- emit simulation plans with no side effects;
- atomically restore a previously validated canonical file, refusing replacement unless
  overwrite is explicit; and
- accept the historical `normalization_rules` input name while emitting the canonical
  `normalization` field.

## Consequence

P2-003 and P2-004 gain testable schema and operator contracts without arbitrary code
loading. Lint/test/diff/simulate output is deterministic and reviewable, while
validation and normalization declarations remain data-only. Control-pack signing,
installation, approval publication, Rule Studio, and validation/normalization runtime
adapters remain separate tasks.

## Reversibility

Additive v1 fields may be introduced with compatibility tests. Semantic breaks require
a new major schema version, migration notes, and a compatibility reader. The atomic
rollback operation changes only its explicit local output file and performs no rule or
financial execution.
