# Local Auth And RBAC

Implemented:

- Local users with PBKDF2 password hashing.
- Built-in roles: admin, controller, preparer, reviewer, auditor-readonly.
- RBAC permissions for DB, users, roles, audit, workflow, master data, finance-core read/manage/validate, inventory read/manage/post/count/reorder/valuation/valuation-reversal, account reconciliation, close, approvals, evidence, journals, intercompany, controls, matching, exceptions, metrics, and ops.
- Studio auth-required mode and local API bearer sessions.

Partially implemented:

- SoD checks exist for workflow transitions, selected finance lifecycle actions, known-user creator/validator separation on finance-core ledger entries, creator/poster separation on inventory movements, creator-or-submitter/approver separation on inventory counts, and creator/approver separation on FIFO valuations and valuation reversals.
- Trusted local CLI labels can still operate without a user record.

Roadmap:

- Configurable role policies.
- SSO/OIDC/SAML and SCIM design before implementation.

Not supported:

- External identity provider integration.
- Hosted production identity.
- Legal sign-off signatures.
