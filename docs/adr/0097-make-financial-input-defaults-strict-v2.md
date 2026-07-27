# ADR 0097: Make public financial-input defaults strict v2

- Status: Accepted
- Date: 2026-07-27
- Scope: P0-005 financial input defaults and compatibility migration

## Context

Current CLI, API, demo, worker, and durable-artifact writers already selected
`strict-financial-input-v2`, but 52 public or model/service defaults across 23
files still selected `legacy-financial-input-v1`. A direct Python caller could
therefore pass a binary float after irreversible approximation and affect an
amount, tolerance, rate, threshold, filter, rule, or reconciliation result.
Warnings and AST call-site inventories reduced exposure but did not satisfy the
P0 rule that binary float must not have an implicit financial effect.

Historical artifacts and integrations still require an explicit compatibility
reader. Removing the legacy policy entirely would unnecessarily break replay.

## Decision

1. Change every `FinancialInputPolicy` default to
   `strict-financial-input-v2`, including `parse_amount`, currency-precision
   parsing, `Money`, configuration/model validation, reconciliation, rules,
   Studio, anonymization, generation, variance, review, reports, and evidence.
2. Make `Money` multiplication/division strict because those operators have no
   policy argument. Exact text, integer, and `Decimal` scalars remain valid;
   binary floats fail visibly.
3. Preserve `legacy-financial-input-v1` only as an explicit argument and in
   versioned historical readers whose schema or persisted record implies it.
   Named legacy scalar helpers remain compatibility APIs and are prohibited at
   production call sites by AST tests.
4. Make new direct artifacts current by default: client-pack schema v2,
   evidence-index schema v3, anonymization manifest v2, synthetic manifest v2,
   variance schema v3, and current matching/report policies record strict v2.
5. Retain exact legacy replay behavior when the caller explicitly supplies the
   legacy policy. Do not silently reinterpret historical artifact versions.

## Compatibility and migration

This is an intentional breaking default for direct Python callers. Replace
financial float literals with `Decimal`, integer minor units, or exact strings:

```python
Money("10.25", "USD")
ReconForgeConfig(amount_tolerance="0.05")
```

Temporary replay of a known legacy contract must be explicit and auditable:

```python
parse_amount(legacy_value, input_policy=LEGACY_FINANCIAL_INPUT_POLICY)
```

New business flows must not select the legacy policy. Historical readers remain
version-scoped compatibility, not a recommendation for new integrations.

## Consequences

- Binary float no longer has an implicit financial effect through a public
  default.
- Exact string, `Decimal`, integer, and historical explicit-legacy behavior
  remain available.
- Callers that relied on warning-only float acceptance must migrate before the
  next release. The changelog and migration guide record the break.
- Supported-version/backend parity, hosted CI, and live service execution remain
  governed separately; this decision is not a universal backend claim.

## Rollback

Do not restore legacy defaults. If an integration cannot migrate immediately,
select the legacy policy explicitly at that integration boundary, record its
owner and removal date, and keep new internal callers prohibited by the AST
gate.
