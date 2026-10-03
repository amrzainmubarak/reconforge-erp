# Retain bounded notification-inbox publications as auditable control-plane evidence

Status: accepted for the inbox implementation slice; storage migration, route registration, backup admission, and Studio navigation are assembled by the integration owner.
Date: 2026-10-03
Scope: Platform Core notification inbox.

ReconForge needs a user-visible operational inbox for review requests, failed
jobs, control exceptions, and available evidence. A generic notification table
or a transport-provider payload would permit arbitrary links, sensitive content,
and non-repeatable actions. It would also make it impossible to prove that an
acknowledgement corresponds to the original notification.

The inbox accepts a closed, versioned envelope only. It stores the authorized
tenant/workspace and optional organization/legal-entity scope, recipient,
publisher, enumerated topic, bounded resource reference, publisher-scoped
idempotency key, publication digest, and UTC timestamp. It deliberately stores
no message body, amount, URL, credential, transport address, or automatic
action. The UI renders the resource reference as text and directs the user to
the separately authorized business workspace.

Each publication is immutable. A read acknowledgement is a separate append-only
row keyed by tenant, workspace, notification, and recipient. The first successful
publication and first acknowledgement each append one audit event and one Outbox
event in the same transaction. An exact replay returns the retained publication;
a changed payload with the same publisher/workspace/key fails with a conflict.
The acknowledgement is idempotent and never writes duplicate evidence.

SQLite uses explicit admission and immutability triggers, local role checks,
and an immediate transaction. PostgreSQL uses forced RLS plus current identity,
role-permission, workspace/organization/legal-entity grant, and active-master
checks. PostgreSQL request scope is set transaction-locally and the repository
rechecks authority before every read, publication, and acknowledgement. A
recipient cannot enumerate another recipient's inbox or acknowledge an unseen
record.

Two permissions define the boundary:

- `notifications.read` permits a current authorized user to enumerate and
  acknowledge only their own scoped inbox records.
- `notifications.publish` permits a current authorized user to create a bounded
  operational notification for a recipient who currently holds
  `notifications.read` in the same scope.

The storage adapters expose a backend-neutral application service and the route
module exposes `GET /notifications/workspaces`, `GET /notifications/inbox`,
`POST /notifications/inbox`, and
`POST /notifications/inbox/{notification_id}/read`. Browser acknowledgement is
CSRF-protected. The React component verifies a closed response contract before
rendering, clears private state on session recovery or permission loss, uses
Arabic RTL labels, and shows no navigable external links.

The independent SQLite verifier validates retained scope hierarchy, historical
identity existence, canonical digests, UTC ordering, and the exact paired
audit/Outbox payloads. Disabled users and revoked permissions intentionally do
not invalidate already retained evidence; they only fail current access.

Integration requirements are explicit. The SQLite schema constant must be
installed by a new ordered migration after its referenced `workspaces`,
`organizations`, `legal_entities`, `users`, `roles`, `permissions`,
`role_permissions`, `audit_events`, and `outbox_events` tables exist. The
PostgreSQL constant must be installed by an Alembic revision after the identity,
scope-grant, workspace, master-data, audit, and Outbox schemas. The application
factory must register the router. The local backup exporter and restore verifier
must retain these two tables and all five inbox triggers, then call
`verify_sqlite_inbox_storage` before admitting a restored database. Studio
navigation is registered separately so the component is reachable without
changing the shared navigation from this slice.

Rollback preserves inbox publications, acknowledgements, audit events, and
Outbox events. A reader without this schema must refuse a backup containing
inbox evidence rather than discard it. A migration downgrade must refuse when
any inbox row exists. No outbound email, webhook delivery, push transport, or
automatic financial approval is implied by this inbox.
