# ADR 0197: Govern real integrations and monotonic evidence retention

- Status: Accepted
- Date: 2026-07-30
- Scope: E-193 / P3-ENT-006 integration and retention administration

## Context

The PostgreSQL server profile already persisted federation links, SCIM and
service-account credentials, notification routes, and evidence metadata. It did
not have one disclosure-bounded administrative surface for disabling those real
resources, and evidence retention was optional metadata that an old metadata
update could remove or shorten. Creating a second generic connector registry
would have produced a shadow state that did not control runtime behavior.

## Decision

1. The administration surface projects the existing authoritative
   `federation_identity_links`, `scim_credentials`, `service_accounts`, and
   `notification_routes` rows. It does not create a duplicate connector table.
2. Integration responses expose kind, stable resource identifier, state,
   lifecycle/count metadata, timestamps, and SHA-256 state/scope digests only.
   Tokens, token hashes, external-subject hashes, notification destinations,
   secret references, and actor identities are not returned.
3. Disable operations require a human `security.policy.manage` principal,
   current privileged assurance, a closed reason code, and the exact state
   digest. The native resource transition, credential revocation where
   applicable, native lifecycle event, and bounded domain-audit event share one
   tenant-scoped transaction.
4. Evidence-retention policies are tenant-scoped, versioned, optimistic, and
   retired rather than deleted. Assignments are append-only and bind the policy
   lifecycle version, evidence retention version, actor, reason, and effective
   timestamps.
5. Applying a policy may extend but never shorten an existing evidence-retention
   floor. The authoritative evidence row enforces monotonic retention and an
   exact version transition in PostgreSQL. The historical evidence registration
   adapter preserves an omitted retention value and rejects an explicitly
   shorter one before SQL.
6. Retention is a metadata floor. This slice does not claim that an external
   object store, backup, replica, or exported copy received a matching WORM lock.

## Consequences

- Disabling an integration changes the same rows used by federation login, SCIM
  authentication, service-account authentication, and notification resolution;
  administration state cannot drift from runtime state.
- Signed keyset cursors bind tenant, resource, filter, ordering, and tie-breaker.
  Stale state/version updates fail closed, while an exact retention-assignment
  replay returns the existing assignment without another effect.
- Migration 0052 adds retention policies, append-only assignment evidence, and
  the evidence-retention version/floor guards under forced tenant RLS.
- This remains single-node synthetic PostgreSQL evidence. It is not connector
  interoperability, secret rotation orchestration, legal-retention advice,
  object-lock assurance, compliance certification, or Enterprise readiness.

## Rollback

An unchanged migration may downgrade `0052` to `0051` with the previous code.
Downgrade refuses if a policy/assignment exists or any evidence row advanced its
retention version. Preserve the database, restore a verified backup, or migrate
the governed evidence through an explicitly reviewed successor. Never drop the
tables/column or shorten retention to force a rollback.
