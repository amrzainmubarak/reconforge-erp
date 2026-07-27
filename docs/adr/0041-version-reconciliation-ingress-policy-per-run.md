# ADR 0041: Version Reconciliation Ingress Policy Per Run

- Status: Accepted; management-pack current schema selection superseded by ADR 0042
- Date: 2026-07-25
- Scope: Stock/GL and deterministic platform matching ingress, writers, and evidence

## Context

ADR 0040 introduced strict and legacy financial-input parsers, but the stock/GL
and platform matching boundaries still selected compatibility behavior only by
an implicit function default. A persisted run therefore could not prove whether
binary floating-point amounts were rejected or accepted through the historical
shortest-text conversion. Changing every public Python default in place would
break existing callers and would also reinterpret historical stored rules that
contain no policy field.

## Decision

Add an explicit `financial_input_policy` to the stock/GL reconciliation and
deterministic matching contracts. Public Python defaults remain
`legacy-financial-input-v1` for compatibility. Current ReconForge writers select
`strict-financial-input-v2` explicitly:

1. Pandas and DuckDB engines, stock/GL CLI workflows, Studio loading, and the
   synthetic enterprise demo run stock/GL or matching under strict v2.
2. The local `match run` command persists strict v2 in `match_jobs.rule_json`
   and `match_rules.rule_json`. Completion audit metadata and transactional
   outbox payloads repeat the selected policy.
3. New PostgreSQL API submissions require strict v2, canonicalize exact
   non-negative `amount_tolerance` text, and reject JSON binary numeric
   tolerances at submission. The worker reads the persisted policy; historical
   rules with no field are explicitly interpreted as legacy v1.
4. A local idempotency key cannot be replayed with a different policy. Such a
   request fails instead of returning evidence produced under another contract.
5. `StockGLReconciliationResult`, `MatchRunResult`,
   `DeterministicMatchOutput`, and engine output expose the applied policy.
   Stock/GL JSON and Excel evidence records it. Management-pack schema v2 makes
   the field required, while its JSON Schema continues to validate historical
   schema v1 artifacts only when the field is absent. ADR 0042 subsequently
   advances current output to schema v3 without changing this v1/v2 contract.

The policy is validated before financial parsing. Strict paths reject Python and
NumPy floating scalars before any string conversion. Invalid stock/GL cells and
canonical matching records remain visible data-quality exceptions; no value is
substituted with zero. Unsupported-policy errors never echo the supplied value.

## Consequences

- The same source records can now be reproduced with a named ingress contract,
  and persisted local/PostgreSQL rules identify that contract.
- CSV and canonical API amount strings remain exact under strict v2. JSON
  numeric amounts are rejected as data quality, and JSON numeric tolerances are
  rejected before a PostgreSQL run is queued.
- Existing direct Python callers retain legacy results and warning behavior.
  Historical database rules remain executable as legacy v1 rather than being
  silently relabeled strict.
- Management-pack schema v2 was the intentional artifact-version change for
  this decision; ADR 0042 later selects schema v3. The
  compatibility branch in the schema preserves validation of schema v1 without
  pretending that v1 contained policy evidence.
- This slice does not prove supported Python-version or live PostgreSQL parity;
  those gates remain open.

## Rollback

Historical v1 rules and report artifacts remain readable. A current writer may
be temporarily changed to explicit legacy v1 only with a recorded migration
reason and new evidence; it must not omit the policy. Never add strict labels to
historical runs, reuse an idempotency key across policies, or downgrade a schema
v2 management artifact to v1 while retaining the new field.
