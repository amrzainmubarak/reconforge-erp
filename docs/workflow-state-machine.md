# Workflow State Machine Foundation

ReconForge includes a local SQLite-backed workflow state machine foundation for DB-backed workflows.

This is a reusable foundation only. It is not a full enterprise workflow engine, legal sign-off system, audit opinion, signature workflow, SOX/SOC/ISO compliance control, SaaS workflow service, SSO/SCIM integration, or hosted identity layer.

## What It Adds

- Local workflow object status tracking in the ReconForge SQLite database.
- Built-in transition templates for `generic_review`, `reconciliation`, `close_task`, `control_test`, and `evidence_requirement`.
- Transition validation for allowed `from_status` and `to_status` pairs.
- Reason enforcement for transitions that require a local explanation.
- Optional RBAC checks when the actor maps to a local user.
- Separation-of-duties checks for prepare/review and submit/approve patterns when a local user is involved.
- Audit events for successful workflow transitions.

## CLI Commands

Initialize or migrate the DB first:

```bash
reconforge db init --db output/reconforge.db
```

Inspect transition templates:

```bash
reconforge workflow transitions --db output/reconforge.db --object-type reconciliation
```

Initialize and inspect a workflow object:

```bash
reconforge workflow init-object --db output/reconforge.db --object-type reconciliation --object-id REC-001 --status Draft
reconforge workflow status --db output/reconforge.db --object-type reconciliation --object-id REC-001
```

Perform a transition:

```bash
reconforge workflow transition --db output/reconforge.db --object-type reconciliation --object-id REC-001 --to-status Prepared --actor local-cli --reason "Prepared for review"
```

Inspect local history:

```bash
reconforge workflow history --db output/reconforge.db --object-type reconciliation --object-id REC-001
```

## Boundaries

- Existing JSON workflows are not migrated or forced through this state machine in this slice.
- Account reconciliation lifecycle, close engine depth, approvals, certifications, and Studio/API action coverage remain foundation-stage and are not full workflow products.
- SSO and SCIM remain deferred.
- Trusted local mode is allowed when no local user is resolved for an actor label.
- Audit events provide checksum integrity aids only; they are not legal signatures or non-repudiation controls.
- This does not create compliance certification, audit sign-off, production enterprise identity, or SaaS workflow capabilities.
