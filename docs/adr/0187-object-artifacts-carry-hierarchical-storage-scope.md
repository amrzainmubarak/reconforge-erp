# ADR 0187: Object artifacts carry hierarchical storage scope

Status: Accepted

## Context

Tenant-only object keys allow two workspaces or legal entities in the same tenant to address the same artifact name. Database RLS cannot protect bytes after they leave PostgreSQL, and trusting only a caller-provided key leaves cross-workspace reads possible.

## Decision

Official object stores accept an immutable, validated tenant/workspace/entity scope. Keys include every supplied hierarchy segment, and integrity metadata repeats the exact hierarchy alongside the SHA-256 digest. Reads fail when either the scoped key is absent or the stored hierarchy metadata differs. A legal entity cannot be supplied without a workspace.

The evidence application passes its authoritative workspace to capable stores and verifies returned scope before creating a registry row. The historical tenant-string protocol remains a compatibility boundary for third-party stores; hierarchical support is an explicit capability rather than a silently breaking protocol change.

## Consequences

- Identical artifact names in sibling workspaces or entities resolve to different immutable objects.
- Local and S3-compatible official stores enforce the same key and metadata contract.
- Existing tenant-only providers remain readable but do not support an Enterprise multi-workspace isolation claim.
- PostgreSQL export authorization and database row scope remain separate P3-ENT-004 work; this ADR does not claim those gates are complete.
