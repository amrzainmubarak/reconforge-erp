# ADR 0256: Field-level policy and masking are explicit

## Decision

Central policy evaluation may receive requested and authorized field-name sets. Any requested field outside the authorized set is denied with a stable reason code. A separate pure projection primitive can mask authorized sensitive fields and reports masked and denied names plus a deterministic digest.

Masking never grants authorization, and the primitive does not recurse into arbitrary objects or imply that every API/UI surface has migrated.

## Boundary

This is a reusable authorization primitive. Route-by-route adoption, provider-specific classification, PostgreSQL policy administration, and complete browser field coverage remain separate evidence gates.
