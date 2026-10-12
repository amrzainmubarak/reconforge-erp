# ADR 0704: Individual Cashflow API Uses Fail-Closed Field Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: The local-only Individual Cashflow API returns a deterministic,
  non-posting control run containing budget and actual Money values, decision
  explanations, input digests, and status counts. Returning the domain
  dictionary directly would allow future result fields to expand the API
  response without a reviewed disclosure decision.
- **Decision**: Apply a central recursive allowlist to the cashflow run,
  decisions, canonical Money objects, input digests, and known status counts.
  Unknown top-level, decision, Money, and status fields are dropped before
  serialization; malformed nested collections fail closed.
- **Verification**: `tests/test_field_access.py` covers nested decisions,
  Money values, known status counts, and synthetic future fields.
  `tests/test_api_individual_cashflow.py` injects future result fields through
  the authenticated local route and proves they do not escape.
  Focused selectors pass, and the full Python regression passes 100%. Ruff,
  Mypy across 539 source files, Bandit, pip-audit, package build, source YAML
  validation across 174 files, and diff checks also pass. pip-audit reports
  the local distribution as unauditable because it is not published on PyPI.
- **Compatibility**: The local-only, non-posting behavior and known run
  fields remain unchanged. This is a bounded disclosure control, not universal
  field-level authorization or production readiness.
- **Rollback**: Revert E-1044 code, tests, this ADR, manifest entry, and
  execution metadata together. Do not restore direct domain-dictionary
  serialization without replacement allowlists and regression evidence.
