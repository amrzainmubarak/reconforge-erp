# Reconciliation Certification Metadata

ReconForge supports lightweight preparer/reviewer metadata in the local exception review state and exported registers.

These fields are workflow metadata only. They are not a legal sign-off, audit opinion, compliance certification, tax advice, assurance conclusion, or digital signature.

## Fields

The local review state can store:

- `prepared_by`
- `prepared_at`
- `reviewed_by`
- `reviewed_at`
- `certification_status`
- `certification_note`

Allowed certification statuses are:

- Draft
- Prepared
- Reviewed
- Accepted Risk
- Needs Follow-up

## Command

```bash
reconforge review set-status \
  --input output \
  --exception-id EXC-0001 \
  --status Resolved \
  --prepared-by "Finance Controller" \
  --reviewed-by "Internal Audit" \
  --certification-status Reviewed \
  --certification-note "Reviewed for workflow completeness"
```

Export the register:

```bash
reconforge review export --input output --output output/review_register.xlsx
```

## Integrations

Certification metadata appears in:

- `output/review_state.json`
- `output/review_register.xlsx`
- Evidence register fields when an evidence binder is generated after review state exists
- Management pack certification metadata sheet and JSON payload when review state exists
- Client pack copied review register when included

## Boundaries

ReconForge does not:

- Authenticate preparers or reviewers.
- Enforce segregation of duties.
- Create legal digital signatures.
- Post back to an ERP.
- Certify a reconciliation, control, account balance, or financial statement.

Users are responsible for their own approval policies, access controls, evidence retention, and audit/legal/compliance review.
