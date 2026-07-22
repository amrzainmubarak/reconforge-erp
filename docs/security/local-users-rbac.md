# Local Users And RBAC

ReconForge now includes a local SQLite-backed users and RBAC foundation for DB-backed workflows.

This is a local-first foundation only. It does not add SaaS authentication, hosted identity, SSO, SCIM, SOC/ISO/SOX compliance, production enterprise identity, direct ERP connectors, legal sign-off, audit opinions, or digital signatures.

## What It Adds

- Local users stored in the ReconForge SQLite database.
- Password hashing with stdlib PBKDF2-HMAC-SHA256, per-user random salts, stored iteration counts, and constant-time verification.
- Built-in roles: `admin`, `controller`, `preparer`, `reviewer`, and `auditor-readonly`.
- Built-in permissions for user management, role management, DB read access, audit event read/verify access, reconciliation workflow primitives, control testing, evidence/report reads, organization master data, separate finance-core read/manage/validate actions, and separate inventory read/manage/post/count/reorder/valuation/valuation-reversal actions.
- Role assignment and permission-check helpers for future DB-backed workflows.
- Separation-of-duties primitives for conflicts such as prepare/review and submit/approve on the same object.
- Audit events for local user and role mutations.

## CLI Commands

Initialize or migrate the DB first:

```bash
reconforge db init --db output/reconforge.db
```

Create the first local admin:

```bash
reconforge users init-admin --db output/reconforge.db --username admin
```

Create and manage local users:

```bash
reconforge users add --db output/reconforge.db --username reviewer --role reviewer
reconforge users list --db output/reconforge.db
reconforge users disable --db output/reconforge.db --username reviewer
reconforge users set-role --db output/reconforge.db --username reviewer --role auditor-readonly
reconforge users check-permission --db output/reconforge.db --username reviewer --permission audit.read
```

Inspect roles:

```bash
reconforge roles list --db output/reconforge.db
reconforge roles permissions --db output/reconforge.db --role reviewer
```

Password prompts use hidden interactive input. Do not pass passwords through shell history, scripts, logs, docs, fixtures, or generated output.

## Boundaries

- SSO and SCIM are not implemented.
- Local API bearer sessions and Studio auth-required mode are implemented as local DB-backed foundations. They are not SSO, SAML, OAuth, SCIM, public internet identity, or SaaS authentication.
- RBAC checks are integrated into implemented DB/API/Studio foundation paths where a local user is known, but legacy JSON workflows can still run in trusted local mode.
- Separation-of-duties checks apply to workflow transitions and selected finance lifecycle actions; they are not legal sign-off or compliance conclusions.
- Audit events provide checksum integrity aids for local mutations. They are not legal signatures or non-repudiation controls.
- This is not SOC, ISO, SOX, GDPR, audit, legal, tax, or regulatory compliance.

## Master-data defaults

- `admin` and `controller` receive `master_data.read` and `master_data.manage`.
- `preparer`, `reviewer`, and `auditor-readonly` receive `master_data.read` only.
- API mutations always require `master_data.manage`.
- CLI mutations enforce RBAC when `--actor` matches a local username; the trusted `local-cli` label remains available for local single-user compatibility and is audit-recorded.

## Finance-core defaults

- `admin` and `controller` receive `finance_core.read`, `finance_core.manage`, and `finance_core.validate`.
- `preparer` receives `finance_core.read` and `finance_core.manage`.
- `reviewer` receives `finance_core.read` and `finance_core.validate`.
- `auditor-readonly` receives `finance_core.read` only.
- A known local creator cannot validate the same ledger-control entry, even when the role has both manage and validate permissions.
- Trusted `local-cli` calls remain available for single-user local operation; this compatibility path is not an enterprise SoD claim.

## Inventory-core defaults

- `admin` and `controller` receive `inventory.read`, `inventory.manage`, and `inventory.post`.
- `preparer` receives `inventory.read` and `inventory.manage`.
- `reviewer` receives `inventory.read` and `inventory.post`.
- `auditor-readonly` receives `inventory.read` only.
- A known local creator cannot post the same inventory movement, even when the role has both manage and post permissions.

## Inventory-planning defaults

- `admin` and `controller` receive count manage/approve and reorder manage permissions.
- `preparer` receives count manage and reorder manage permissions.
- `reviewer` receives count approve permission.
- All built-in inventory roles retain `inventory.read`; `auditor-readonly` remains read-only.
- A known local user cannot approve a count they created or submitted. Submitted cancellation also requires the approval permission.
- Trusted `local-cli` calls remain available for single-user local operation; this compatibility path is not an enterprise SoD claim.

## Inventory-valuation defaults

- `admin` and `controller` receive `inventory.valuation.manage` and `inventory.valuation.approve`.
- `preparer` receives `inventory.valuation.manage`.
- `reviewer` receives `inventory.valuation.approve`.
- `auditor-readonly` receives no mutation permission and retains valuation visibility through `inventory.read`.
- A known local user cannot approve a valuation they created. Approval creates a balanced Finance Core Draft but does not grant or invoke `finance_core.validate`.
- Trusted `local-cli` calls remain available for single-user local operation; this compatibility path is not an enterprise SoD or accounting-approval claim.

## Inventory-valuation-reversal defaults

- `admin` and `controller` receive `inventory.valuation.reverse.manage` and `inventory.valuation.reverse.approve`.
- `preparer` receives `inventory.valuation.reverse.manage`.
- `reviewer` receives `inventory.valuation.reverse.approve`.
- `auditor-readonly` receives no reversal mutation permission and retains visibility through `inventory.read`.
- A known local user cannot approve a reversal they created. Approval applies exact protected FIFO effects and creates a balanced Finance Core Draft but does not grant or invoke `finance_core.validate`.
