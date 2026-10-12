# ADR 0711: Metrics API Uses Fail-Closed Field Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: Local metric dashboard reads used `SELECT snapshot.*` and the
  API returned the resulting dictionaries directly. PostgreSQL selected a
  narrower shape, so backend choice could change the response disclosure
  boundary and future SQLite columns could escape.
- **Decision**: Project dashboard snapshots and metric lineage definitions
  through separate central allowlists at the API boundary. Unknown adapter or
  storage fields are dropped before serialization.
- **Verification**: `tests/test_field_access.py` covers both allowlists and
  `tests/test_api_metrics.py` injects future fields through the server HTTP
  route and proves they are absent from both responses.
- **Compatibility**: Metric computation, exact `value_text`, lineage content,
  tenant policy, and local/PostgreSQL repository behavior are unchanged.
- **Rollback**: Revert E-1051 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct `SELECT *` disclosure.
