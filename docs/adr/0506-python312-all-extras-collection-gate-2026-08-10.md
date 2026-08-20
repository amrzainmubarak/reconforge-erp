# ADR 0506: Python 3.12 all-extra collection gate

- **Date**: 2026-08-10
- **Decision**: Retain a clean isolated Python 3.12 collection result using
  the locked all-extra profile for the historical CI import-error surface.
- **Evidence**: `uv run --isolated --python 3.12 --all-extras --locked
  --no-editable pytest --tb=short -ra` over the seven affected test modules
  reports 48 passed, one declared PostgreSQL capability skip, and one existing
  Starlette deprecation warning.
- **Boundary**: This proves dependency installation and local test collection
  in an isolated Windows Python 3.12 environment. It does not replace hosted
  CI, live PostgreSQL, native backup tools, or release attestation.
- **Rollback**: Remove this evidence-only ADR and the E-670 execution entries;
  no product code, schema, or persisted customer data changes are involved.
