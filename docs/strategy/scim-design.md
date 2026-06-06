# SCIM Design Only

Status: roadmap design only. Not implemented.

Direction:

- Treat SCIM as optional user provisioning for local users.
- Support create, update, disable, and role/group mapping only after the identity boundary is mature.
- Write audit events for provisioning and deprovisioning.
- Keep local admin recovery available.

Security boundaries:

- SCIM bearer credentials require a secret storage design first.
- Deprovisioning must revoke local sessions.
- Group-to-role mapping must be explicit and deny by default.

Not supported today:

- SCIM endpoints.
- External provisioning.
- Automatic role sync.
