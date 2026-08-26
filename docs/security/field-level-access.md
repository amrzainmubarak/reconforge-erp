# Field-level access

`CentralPolicyEngine` supports an explicit requested-field versus authorized-field contract. The contract denies by default when a requested field is outside the authorized set. `project_fields` then produces an allowlisted projection, replacing explicitly masked fields with `[REDACTED]` and retaining deterministic masked/denied evidence.

This does not claim that all existing routes or UI components have migrated. Integrators must supply field sets from a versioned policy and test each sensitive surface.

## E-1017 migrated surface

The local and Server Profile `GET /api/v1/evidence/records/{evidence_id}/drill-down`
surface now consumes a single evidence response allowlist.  Ordinary reads
receive the non-sensitive projection; `include_sensitive=true` still requires
`evidence.manage`, requests the reviewed complete field set through the Server
Profile central policy boundary, and remains subject to the allowlist.  Nested
evidence links are projected independently.  Unknown future fields are
dropped, and each evidence node returns projection version, mode, masked and
denied fields, and a deterministic digest.  The existing `***redacted***`
token is retained at this API boundary for compatibility.

This is one migrated surface, not universal field-level authorization or
production IAM effectiveness.  The complete decision and rollback boundary
are recorded in ADR 0677.

E-1018 extends the same boundary to the evidence list, single-record get, and
Server Profile registration response. List/get use the safe projection;
registration uses the reviewed sensitive allowlist after `evidence.manage`
authorization. The projection metadata remains additive and unknown adapter
fields are dropped. ADR 0678 records this extension and its limits.

## E-1019 migrated surface

The legacy `GET /api/v1/audit/events` response now uses one central allowlist
for both the local SQLite and PostgreSQL adapter shapes. Actor and tenant
identity, object/resource identifiers, request IDs, reasons, and decoded
metadata are masked with `[REDACTED]`; unknown adapter fields are dropped.
The route retains its existing `audit.read` requirement and Server Profile
tenant-policy re-check. This is a disclosure boundary for one legacy response
family, not universal field-level authorization or production IAM. ADR 0679
records the decision and rollback.

## E-1020 migrated surface

Server Profile evidence requirement and checksum verification mutation
responses now consume closed allowlists. Known fields needed by the existing
authorized operation remain available, deterministic `field_access` metadata
is additive, and unknown adapter fields are dropped. This covers two mutation
response contracts and does not establish universal field-level authorization
or production IAM. ADR 0680 records the decision and rollback.

## E-1021 migrated surface

The `/api/v1/close` period, task, and readiness responses now use central
allowlists for the union of the local SQLite and PostgreSQL shapes. This
prevents SQLite `SELECT *` schema growth or a future adapter field from
silently expanding the response. Existing fields and route permissions are
preserved. This is a bounded disclosure control, not universal field-level
authorization or production IAM. ADR 0681 records the decision and rollback.

## E-1022 migrated surface

The local `/api/v1/exceptions` list, assignment, and status responses now use a
central exception-record allowlist. This prevents `SELECT *` schema growth or
future storage fields from silently expanding the API while preserving the
existing response envelope and RBAC boundary. The route remains explicitly
local-only. This is a bounded disclosure control, not universal field-level
authorization or production IAM. ADR 0682 records the decision and rollback.

## E-1023 migrated surface

Consolidation-close period and run responses now use central allowlists for the
reviewed local SQLite and PostgreSQL shapes. Journal lines, effect records, and
effect lines are projected independently; reviewed PostgreSQL evidence arrays
remain available while internal worksheet payload/cache fields and unknown
future adapter/storage fields are excluded. This is a bounded disclosure
control for the consolidation-close response family, not universal
field-level authorization or production IAM. ADR 0683 records the decision
and rollback.
