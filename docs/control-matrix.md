# Control Matrix

ReconForge can generate a local control matrix from a rule pack. This helps controllers, consultants, and internal audit teams review which deterministic checks exist, what evidence fields they reference, and where local owner/frequency placeholders still need to be assigned.

The control matrix is not a compliance certification, legal conclusion, audit opinion, or vendor endorsement.

## Command

```bash
reconforge controls matrix --pack control-packs/audit-basic --output output/control_matrix
```

Outputs:

- `output/control_matrix/control_matrix.xlsx`
- `output/control_matrix/control_matrix.csv`
- `output/control_matrix/control_matrix.json`
- `output/control_matrix/control_matrix.md`

## Columns

The generated matrix includes:

- `control_id`
- `rule_id`
- `control_description`
- `risk_area`
- `severity`
- `expected_evidence`
- `owner_placeholder`
- `frequency_placeholder`
- `related_exceptions_placeholder`
- `recommended_action`
- `risk_impact`
- `business_impact`
- `source_file`
- `pack_id`
- `pack_name`

`owner_placeholder`, `frequency_placeholder`, and `related_exceptions_placeholder` are placeholders for local workflow documentation. ReconForge does not assign users, enforce RBAC, or certify control operation.

## Rule Pack Source

The command reads:

- `pack.yml`
- `rules.yml`
- `expected-exceptions.md` when present

YAML loading is routed through the existing safe rule-pack loader and pydantic models.

## Security Notes

- The command uses local rule-pack files only.
- Malformed control packs return a concise CLI error.
- Markdown output escapes angle brackets in user-controlled rule text.
- No cloud service, telemetry, external framework mapping, or direct ERP connector is used.
