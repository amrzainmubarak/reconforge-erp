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
