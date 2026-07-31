# ADR 0188: Enterprise exports are authorized RLS snapshots

Status: Accepted

## Context

Writing a tenant or workspace identifier into a filename does not prove that the exported rows came from that scope. A safe Enterprise export needs the same authorization and database isolation as an interactive read, deterministic identity, bounded resource use, and immutable storage publication.

## Decision

The first Enterprise export is a bounded control-plane snapshot. It requires explicit tenant and workspace scope, optional organization/entity scope, the existing `reports.read` permission, and exact authorized-scope grants. PostgreSQL transaction-local settings are installed before any static allowlisted query, and RLS remains the authoritative row filter.

Migration 0043 replaces permissive tenant-only Evidence Application policies with workspace policies, links legal entities and branches to the active workspace through their organization, and aligns the transaction's `app.entity_id` alias with its legal-entity scope. Entity exports omit workspace-only Evidence records because the current Evidence aggregate has no authoritative entity attribution.

The snapshot sorts rows and datasets canonically, records per-dataset and artifact digests, caps every dataset at 10,000 rows and the artifact at 32 MiB, excludes raw source paths and idempotency keys, and publishes to hierarchy-aware immutable object storage. Digest-addressed replay reads and verifies the existing object rather than replacing it.

## Consequences

- Sibling workspace/entity rows are excluded by live non-superuser PostgreSQL RLS, not by filename convention alone.
- Authorization denial, snapshot failure, and storage failure occur before a published artifact is returned.
- The export is a control-plane metadata artifact, not a full financial-data export or disclosure approval.
- Entity-attributed Evidence requires a future versioned model change; silently assigning workspace Evidence to an entity is forbidden.
