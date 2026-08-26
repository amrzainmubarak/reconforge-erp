# ADR 0666: Disposable PostgreSQL identity and retention governance runtime

- Status: Accepted
- Date: 2026-08-26
- Owners: Platform / Security / SRE

## Context

The repository had live-gated identity and retention governance tests, but the
available local PostgreSQL containers were not a single clean current-head
fixture. One had an older Alembic head and another did not contain migration
metadata. Reusing either would weaken the evidence boundary and make a current
Team/Enterprise governance claim ambiguous.

## Decision

Create a newly labelled disposable PostgreSQL `17.10-alpine` container and
migrate it from empty state to the current Alembic head
`0092_pg_close_lock_evidence`. Create a dedicated application role with
`rolsuper=false` and `rolbypassrls=false`, grant only the schema/table/sequence/
function privileges needed by the live contract, and run the focused security
governance and identity administration selectors.

Record only synthetic, non-secret runtime facts in a closed JSON report. Bind
the report to its schema, migration head, image digest, role posture, observed
controls, and a canonical structural digest. Keep all Team/Enterprise/Regulated
readiness statuses unchanged.

## Verification and boundaries

E-972 passed both live selectors (`2/2`) against the fresh fixture. The runtime
observed tenant isolation, atomic retention policy lifecycle, retention-floor
non-shortening, identity session invalidation, step-up, and last-administrator
guards.

The evidence is one local Docker host with synthetic tenants and credentials. It
does not prove external IdP/SSO/SCIM interoperability, distributed session
revocation, HA/DR, legal hold, WORM, privacy erasure, regulated review, or
production IAM assurance.

## Rollback

Remove the disposable labelled container after capturing the report and revert
the report, schema, test, manifest, and documentation references. No product
database migration or runtime code rollback is required.
