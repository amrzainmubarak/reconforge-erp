"""Generate local mapping profile authoring templates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from reconforge.io.writers import ensure_output_dir


@dataclass(frozen=True)
class ProfileTemplateArtifacts:
    """Generated profile template paths."""

    mapping_template_path: Path
    guide_path: Path


def _template_payload() -> dict[str, object]:
    return {
        "profile_id": "custom-export-profile",
        "source_system": "generic_csv",
        "version": "0.1.0",
        "description": "Export-based mapping template. This is not a direct ERP connector.",
        "export_workflow": {
            "mode": "export_based",
            "cloud_upload_required": False,
            "direct_api_connector": False,
            "notes": [
                "Export CSV/XLSX reports from the ERP or data warehouse to a local folder.",
                "Map source columns into ReconForge canonical CSV files before reconciliation.",
            ],
        },
        "canonical_datasets": {
            "stock_moves.csv": {
                "source_reports": ["Inventory movement export"],
                "purpose": "Inventory movement rows for reconciliation and controls.",
            },
            "gl_entries.csv": {
                "source_reports": ["General ledger line export"],
                "purpose": "Posted accounting rows for stock-to-GL review.",
            },
        },
        "field_mappings": {
            "stock_moves.csv": {
                "move_id": ["source_move_id"],
                "date": ["movement_date"],
                "source_document": ["source_document"],
                "work_order": ["work_order"],
                "product_code": ["item_code"],
                "product_name": ["item_name"],
                "category": ["category"],
                "quantity": ["quantity"],
                "unit_cost": ["unit_cost"],
                "total_cost": ["total_cost"],
                "warehouse": ["warehouse"],
                "movement_type": ["movement_type"],
                "customer_code": ["customer_code"],
                "equipment_serial": ["equipment_serial"],
                "created_by": ["created_by"],
            },
            "gl_entries.csv": {
                "entry_id": ["source_entry_id"],
                "date": ["posting_date"],
                "journal": ["journal"],
                "account_code": ["account_code"],
                "account_name": ["account_name"],
                "reference": ["reference"],
                "source_document": ["source_document"],
                "debit": ["debit"],
                "credit": ["credit"],
                "amount": ["amount"],
                "cost_center": ["cost_center"],
                "work_order": ["work_order"],
                "created_by": ["created_by"],
            },
        },
        "join_keys": {
            "stock_to_gl": {
                "stock_side": ["source_document", "date", "total_cost"],
                "gl_side": ["source_document", "date", "amount"],
            },
        },
        "quality_checks": [
            "Confirm the stock and GL exports cover the same period.",
            "Confirm sign conventions for amounts before reconciliation.",
            "Confirm source-document fields are exported where possible.",
        ],
    }


def write_profile_template(output_path: Path | str) -> ProfileTemplateArtifacts:
    """Write a local generic CSV mapping template and authoring guide."""

    output_dir = ensure_output_dir(output_path)
    mapping_template_path = output_dir / "mapping_template.yml"
    with mapping_template_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(_template_payload(), handle, sort_keys=False)
    guide_path = output_dir / "profile_authoring_guide.md"
    guide_path.write_text(
        "\n".join(
            [
                "# ReconForge Mapping Profile Authoring Guide",
                "",
                "This guide helps create export-based ReconForge mapping profiles from local CSV/XLSX reports.",
                "",
                "It does not create a direct ERP connector, store credentials, upload data, or certify ERP compatibility.",
                "",
                "## Steps",
                "",
                "1. Copy `mapping_template.yml` into a new control-pack folder as `mapping.yml`.",
                "2. Replace placeholder source column names with sanitized export headers.",
                "3. Keep `export_workflow.mode` set to `export_based` unless a separately implemented connector exists.",
                "4. Add rule-pack files: `pack.yml`, `rules.yml`, `risk_model.yml`, `README.md`, `expected-exceptions.md`, and `sample-command.md`.",
                "5. Validate with `reconforge mappings validate --pack control-packs/<pack-name>`.",
                "",
                "Use synthetic or anonymized examples only. Do not commit customer, supplier, employee, invoice, asset, GL, or financial data.",
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    return ProfileTemplateArtifacts(mapping_template_path=mapping_template_path, guide_path=guide_path)
