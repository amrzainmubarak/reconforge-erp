# ADR 0698: Professional invoice/payment API uses fail-closed field projection

- Status: Accepted for E-1038
- Date: 2026-08-26
- Scope: Professional invoice/payment evidence response serialization

## Context

The professional invoice/payment API persists and returns a deterministic,
non-posting evidence run. Its response contains a storage envelope and a
nested report with canonical money objects, status counts, and decisions. Local
SQLite and tenant-scoped PostgreSQL adapters can evolve independently, so
directly serializing their mappings would let future fields enter a financial
evidence response without a reviewed contract change.

## Decision

Use central field-access projections for all three response operations:

- project the run envelope with an explicit allowlist;
- project the report and its amount tolerance recursively;
- project each decision and its optional amount variance recursively; and
- retain only the known professional-control status-count keys.

Malformed nested mappings or collections fail closed. The projection is
applied after existing authentication, workspace scope, persistence,
idempotency, and no-network/no-posting behavior. Existing response envelopes,
evidence digests, and canonical financial values remain compatible.

## Consequences

Unknown future adapter or storage fields do not enter the reviewed response
family by default. This is a bounded disclosure control, not universal
field-level authorization or external IAM; distributed revocation, disclosure
approval, source authenticity, and production effectiveness remain separate
gates. No schema, migration, or persistence behavior changes.

## Verification and rollback

`tests/test_field_access.py` covers the recursive projector.
`tests/test_api_professional_invoice_payment.py` injects synthetic future
fields at top-level and nested report, money, decision, and variance levels
across create/list/read responses. Focused tests pass 29 tests plus 1 existing
skip; full Python regression, Ruff, Mypy, Bandit, pip-audit, package build,
targeted YAML, and diff gates pass. The local distribution is not auditable by
pip-audit because it is not published on PyPI.

Rollback is a coordinated revert of the E-1038 route/projector code, tests,
this ADR, manifest entry, and execution metadata. It must not restore direct
unbounded adapter-row serialization without a replacement disclosure control.
