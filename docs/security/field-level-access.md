# Field-level access

`CentralPolicyEngine` supports an explicit requested-field versus authorized-field contract. The contract denies by default when a requested field is outside the authorized set. `project_fields` then produces an allowlisted projection, replacing explicitly masked fields with `[REDACTED]` and retaining deterministic masked/denied evidence.

This does not claim that all existing routes or UI components have migrated. Integrators must supply field sets from a versioned policy and test each sensitive surface.
