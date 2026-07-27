# Rule-Pack Schema Reference

ReconForge control packs are local YAML folders that describe audit controls, source mappings, expected exceptions, and risk guidance. The rule engine currently validates `pack.yml` and `rules.yml` at runtime. `mapping.yml` and `risk_model.yml` are documented conventions and are covered by structure tests for official packs.

## Control Pack Layout

```text
control-packs/example-pack/
├── README.md
├── expected-exceptions.md
├── mapping.yml
├── pack.yml
├── risk_model.yml
├── rules.yml
└── sample-command.md
```

## `pack.yml` Schema

Required fields:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `pack_id` | string | Yes | Stable lowercase identifier, usually matching the folder name. |
| `name` | string | Yes | Human-readable pack name. |
| `version` | string | Yes | Pack version. Keep aligned with release intent where practical. |
| `description` | string | Yes | Short description of control purpose. |
| `owner` | string | No | Defaults to `ReconForge ERP Maintainers`. |
| `tags` | list[string] | No | Search and grouping tags. |

Valid example:

```yaml
pack_id: inventory-review
name: Inventory Review Controls
version: 0.4.0
description: Export-based controls for inventory movement and GL traceability.
owner: ReconForge ERP Maintainers
tags:
  - inventory
  - audit
  - stock-gl
```

Invalid example:

```yaml
pack_id: inventory-review
description: Missing required name and version.
```

Why invalid: `name` and `version` are required.

## `rules.yml` Schema

Top-level field:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `rules` | list[rule] | Yes | Must contain at least one rule. |

Rule fields:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `rule_id` | string | Yes | Stable control identifier, for example `SAP-001`. |
| `rule_name` | string | Yes | Human-readable name. |
| `severity` | enum | Yes | One of `info`, `low`, `medium`, `high`, `critical`. |
| `entity_type` | string | Yes | Business entity, for example `stock_move`, `gl_entry`, `work_order`, `product`. |
| `source_file` | string | Yes | CSV filename. Must end with `.csv`. |
| `condition` | object | Yes | Declarative condition using a supported operator. |
| `message` | string | Yes | Explanation shown in rule outputs. |
| `recommended_action` | string | Yes | Suggested reviewer action. |
| `risk_impact` | integer | Yes | 0 to 100. |
| `business_impact` | string | No | Optional domain impact. |
| `confidence` | number | No | 0 to 1. Defaults to `0.9`. |
| `evidence_fields` | list[string] | No | Fields copied into rule result evidence payload. |

Condition fields:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `operator` | string | Yes | Must be allowlisted. |
| `field` | string | Operator-dependent | Source row field. |
| `value` | any | Operator-dependent | Literal comparison value. |
| `other_field` | string | Operator-dependent | Compare to another field in the same row. |
| `target_file` | string | Cross-file operators | Related CSV filename. |
| `target_field` | string | Cross-file operators | Related target field alias. |
| `source_key` | string | Cross-file operators | Source key field. |
| `target_key` | string | Cross-file operators | Target key field. |
| `aggregate_field` | string | `sum_matches` | Field to sum in target file. |
| `threshold` | number | `variance_above` | Numeric threshold. |
| `bucket_days` | integer | `aging_bucket` | Minimum age in days. |
| `tolerance` | number | Tolerance operators | Absolute tolerance. |
| `days` | integer | Date/aging operators | Day tolerance or age threshold. |
| `conditions` | list[condition] | Logical operators | Nested conditions for `and`, `or`, `not`. |

Valid example:

```yaml
rules:
  - rule_id: INV-001
    rule_name: Missing stock source document
    severity: high
    entity_type: stock_move
    source_file: stock_moves.csv
    condition:
      operator: missing
      field: source_document
    message: Stock movement is missing the source document needed for GL traceability.
    recommended_action: Obtain the source document or document approved exception handling.
    risk_impact: 75
    confidence: 0.95
    evidence_fields:
      - move_id
      - source_document
      - product_code
      - total_cost
```

Valid nested example:

```yaml
rules:
  - rule_id: INV-002
    rule_name: Stock issue without work order
    severity: high
    entity_type: stock_move
    source_file: stock_moves.csv
    condition:
      operator: and
      conditions:
        - operator: missing
          field: work_order
        - operator: in_list
          field: movement_type
          value: [ISSUE, DIRECT_FIT, STOCK_ISSUE]
    message: Stock issue does not reference a work order.
    recommended_action: Link the issue to a valid work order or document the approved non-work-order use.
    risk_impact: 80
    evidence_fields: [move_id, movement_type, work_order, product_code, total_cost]
```

Invalid examples:

```yaml
rules:
  - rule_id: BAD-001
    rule_name: Bad source file
    severity: high
    entity_type: stock_move
    source_file: stock_moves.xlsx
    condition:
      operator: missing
      field: source_document
    message: Bad
    recommended_action: Fix
    risk_impact: 50
```

Why invalid: `source_file` must be a CSV filename.

```yaml
rules:
  - rule_id: BAD-002
    rule_name: Unsupported operator
    severity: high
    entity_type: stock_move
    source_file: stock_moves.csv
    condition:
      operator: run_python
      field: source_document
    message: Bad
    recommended_action: Fix
    risk_impact: 50
```

Why invalid: `run_python` is not an allowlisted operator.

## Supported Operators

Comparison and string operators:

- `equals`
- `not_equals`
- `contains`
- `not_contains`
- `exists`
- `missing`
- `greater_than`
- `less_than`
- `greater_or_equal`
- `less_or_equal`
- `in_list`
- `not_in_list`
- `regex_match`
- `starts_with`
- `ends_with`

Amount, date, and variance operators:

- `amount_within_tolerance`
- `date_within_days`
- `variance_above`
- `aging_bucket`
- `before_date`
- `after_date`

Dataset and cross-file operators:

- `duplicate`
- `unique`
- `cross_file_exists`
- `cross_file_missing`
- `sum_matches`

Logical operators:

- `and`
- `or`
- `not`

## `mapping.yml` Schema

`mapping.yml` explains how source ERP exports map into canonical ReconForge files. v0.4.0 official ERP profiles use the following convention.

Required fields for official ERP mapping profiles:

| Field | Type | Notes |
| --- | --- | --- |
| `profile_id` | string | Stable mapping profile identifier. |
| `source_system` | string | ERP source, for example `odoo` or `sap`. |
| `version` | string | Mapping profile version. |
| `export_workflow` | object | Workflow boundaries, including export-based mode and no cloud requirement. |
| `canonical_datasets` | object | Canonical files and source objects/reports. |
| `field_mappings` | object | Canonical fields mapped to source field candidates. |
| `join_keys` | object | Recommended keys for cross-file matching. |
| `quality_checks` | list[string] | Practical checks before running reconciliation. |

Valid example:

```yaml
profile_id: odoo-inventory-valuation
source_system: odoo
version: 0.4.0
export_workflow:
  mode: export_based
  cloud_upload_required: false
  direct_api_connector: false
canonical_datasets:
  stock_moves.csv:
    source_objects: [stock.move, stock.valuation.layer]
    purpose: Inventory movement and valuation records.
field_mappings:
  stock_moves.csv:
    move_id: [id, stock_move_id, valuation_layer_id]
    date: [date, create_date, accounting_date]
    source_document: [origin, reference, picking_id, description]
join_keys:
  stock_to_gl:
    stock_side: [source_document, product_code, date, total_cost]
    gl_side: [source_document, reference, date, amount]
quality_checks:
  - Confirm all files cover the same accounting period.
```

Invalid example:

```yaml
source_system: odoo
field_mappings:
  stock_moves.csv: {}
```

Why invalid for official profiles: missing `profile_id`, `version`, `export_workflow`, `canonical_datasets`, `join_keys`, and `quality_checks`.

## `risk_model.yml` Schema

`risk_model.yml` documents default risk weighting and escalation guidance for a pack. It is not currently used as the only source of rule severity; each rule still carries its own `severity` and `risk_impact`.

Recommended fields:

| Field | Type | Notes |
| --- | --- | --- |
| `risk_weights` | object | Named risk weights, usually 0 to 100. |
| `escalation` | object | Severity or risk tier to owner/team. |
| `review_guidance` | list[string] | Optional reviewer notes. |

Valid example:

```yaml
risk_weights:
  missing_source_document: 75
  unmatched_gl_entry: 70
  missing_work_order: 80
escalation:
  critical: Finance Controller
  high: Inventory Controller
  medium: Process Owner
  low: Data Steward
review_guidance:
  - Confirm source documents before accepting timing differences.
  - Document accepted risk with reviewer name and date.
```

Invalid example:

```yaml
risk_weights:
  missing_source_document: very-high
```

Why invalid for official profiles: risk weights should be numeric so they can be compared and tested consistently.

## Severity Model

| Severity | Meaning |
| --- | --- |
| `info` | Context or low-risk observation. |
| `low` | Data quality or process issue unlikely to affect close materially. |
| `medium` | Review needed; possible control weakness or reconciliation issue. |
| `high` | Significant traceability, valuation, or financial close risk. |
| `critical` | Severe control failure or high-value exception requiring escalation. |

## Confidence Model

`confidence` is a numeric score from 0 to 1.

- `1.0`: deterministic rule with strong field evidence.
- `0.8` to `0.99`: strong rule but may need process interpretation.
- `0.5` to `0.79`: useful signal with known false-positive risk.
- Below `0.5`: avoid for official packs unless clearly documented.

If omitted, confidence defaults to `0.9`.

## Risk Impact Model

`risk_impact` is an integer from 0 to 100.

- `0` to `24`: informational or low operational impact.
- `25` to `49`: low to medium review risk.
- `50` to `69`: meaningful exception or data quality issue.
- `70` to `89`: high audit/control risk.
- `90` to `100`: critical exception.

Severity and risk impact should be aligned. For example, a `critical` rule with `risk_impact: 20` should be treated as a design error unless justified.

## Evidence Fields

Evidence fields should help a reviewer trace the source record. Use fields such as:

- Record ID: `move_id`, `entry_id`, `work_order`, `invoice_number`, `po_number`.
- Traceability fields: `source_document`, `reference`, `movement_type`.
- Master data: `product_code`, `product_name`, `customer_code`, `account_code`.
- Amount/date fields: `date`, `total_cost`, `amount`, `debit`, `credit`.
- Ownership fields: `cost_center`, `created_by`, `responsible_engineer`.

Do not include fields that expose unnecessary sensitive data.

## Contributor Checklist

Before opening a control-pack pull request:

- Pack has `README.md`, `pack.yml`, `mapping.yml`, `rules.yml`, `risk_model.yml`, `expected-exceptions.md`, and `sample-command.md`.
- `pack_id` matches folder intent and is stable.
- Rules use only supported operators.
- Rules use CSV source files.
- Each rule has practical `message`, `recommended_action`, `risk_impact`, and `evidence_fields`.
- Mapping docs explain source exports without claiming unimplemented direct connectors.
- Expected exceptions explain likely results on sample or real exports.
- Sample commands include validation and run examples.
- Tests are added or updated for new behavior.
- No live ERP data is committed.

## Validation Commands

Validate a pack:

```bash
reconforge rules validate --pack control-packs/audit-basic
```

Validate an ERP mapping profile:

```bash
reconforge mappings validate --pack control-packs/odoo-inventory-valuation
reconforge mappings validate --pack control-packs/sap-mb51-fagll03
```

List rules:

```bash
reconforge rules list --pack control-packs/audit-basic
```

Run rules:

```bash
reconforge rules run --input examples/sample_data --pack control-packs/audit-basic --output output/rules
```

The current CLI loads financial YAML literals under
`strict-financial-input-v2`, preserving unquoted decimal lexemes before
validation. It writes `rule_results.json` schema v2 with the named policy,
normalized executable `pack.yml`/`rules.yml` digest, sorted local CSV byte hashes, deterministic
decision digest, complete artifact digest, and result records. The companion
CSV repeats pack/policy/digest provenance on each triggered row. See
`docs/schemas/rule_results.schema.json`.

The digests detect local content inconsistency; they are not signatures, pack
approval, audit opinions, compliance certifications, or proof that an export
came from its claimed source system. Direct Python rule APIs retain legacy-v1
defaults during the compatibility window, and the historical unversioned
`{"results": [...]}` JSON shape remains readable as `legacy-unverified`.

Explain one rule:

```bash
reconforge rules explain --pack control-packs/audit-basic --rule AB-001
```

Project quality checks:

```bash
python -m ruff check .
python -m mypy reconforge
python -m pytest
python -m bandit -q -r reconforge
```
