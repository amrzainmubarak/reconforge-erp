# ADR 0712: Inventory Void API Uses Fail-Closed Field Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: Inventory movement create, read, list, and post responses used
  the central movement projection, but the void mutation returned the adapter
  record directly. A future SQLite or PostgreSQL movement field could
  therefore escape only through the void response.
- **Decision**: Apply `project_inventory_movement` to both server and local
  void responses at the API boundary. The existing movement allowlist remains
  the single reviewed disclosure contract for all movement lifecycle paths.
- **Verification**: The authenticated server Inventory Core route test now
  exercises the void endpoint with a repository record containing an unknown
  movement field and proves that field is absent from the response.
- **Compatibility**: Void validation, posting/voiding rules, audit behavior,
  tenant scope, and movement values are unchanged; only unknown response
  fields are removed.
- **Rollback**: Revert E-1052 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct adapter serialization.
