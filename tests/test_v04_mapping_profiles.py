from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from reconforge.rules.loader import load_rule_pack
from reconforge.rules.operators import SUPPORTED_OPERATORS

ERP_PROFILE_PACKS = [
    Path("control-packs/odoo-inventory-valuation"),
    Path("control-packs/sap-mb51-fagll03"),
]

REQUIRED_PACK_FILES = {
    "README.md",
    "pack.yml",
    "mapping.yml",
    "rules.yml",
    "risk_model.yml",
    "expected-exceptions.md",
    "sample-command.md",
}

REQUIRED_MAPPING_KEYS = {
    "profile_id",
    "source_system",
    "version",
    "export_workflow",
    "canonical_datasets",
    "field_mappings",
    "join_keys",
    "quality_checks",
}


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_rule_pack_schema_reference_documents_implemented_rules() -> None:
    path = Path("docs/rule-pack-schema-reference.md")
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    for required_section in [
        "## `pack.yml` Schema",
        "## `rules.yml` Schema",
        "## `mapping.yml` Schema",
        "## `risk_model.yml` Schema",
        "## Supported Operators",
        "## Severity Model",
        "## Confidence Model",
        "## Risk Impact Model",
        "## Evidence Fields",
        "## Contributor Checklist",
        "## Validation Commands",
    ]:
        assert required_section in text
    for operator in SUPPORTED_OPERATORS:
        assert f"`{operator}`" in text


def test_erp_mapping_profiles_have_required_structure() -> None:
    for pack in ERP_PROFILE_PACKS:
        assert pack.exists()
        names = {path.name for path in pack.iterdir()}
        assert REQUIRED_PACK_FILES.issubset(names)
        assert (pack / "sample-command.md").read_text(encoding="utf-8").strip()
        assert (pack / "expected-exceptions.md").read_text(encoding="utf-8").strip()


def test_erp_mapping_profiles_have_required_mapping_keys() -> None:
    for pack in ERP_PROFILE_PACKS:
        mapping = _read_yaml(pack / "mapping.yml")
        assert REQUIRED_MAPPING_KEYS.issubset(mapping)
        export_workflow = mapping["export_workflow"]
        assert isinstance(export_workflow, dict)
        assert export_workflow["mode"] == "export_based"
        assert export_workflow["cloud_upload_required"] is False
        assert export_workflow["direct_api_connector"] is False
        assert isinstance(mapping["canonical_datasets"], dict)
        assert "stock_moves.csv" in mapping["canonical_datasets"]
        assert "gl_entries.csv" in mapping["canonical_datasets"]
        assert isinstance(mapping["field_mappings"], dict)
        assert "stock_moves.csv" in mapping["field_mappings"]
        assert "gl_entries.csv" in mapping["field_mappings"]
        assert isinstance(mapping["quality_checks"], list)
        assert mapping["quality_checks"]


def test_erp_mapping_profiles_rules_are_valid_yaml_and_loadable() -> None:
    for pack in ERP_PROFILE_PACKS:
        rules = _read_yaml(pack / "rules.yml")
        assert isinstance(rules.get("rules"), list)
        assert rules["rules"]
        loaded = load_rule_pack(pack)
        assert loaded.rules
        for rule in loaded.rules:
            assert rule.source_file.endswith(".csv")
            assert rule.evidence_fields


def test_erp_mapping_profile_docs_explain_export_based_workflow() -> None:
    for pack in ERP_PROFILE_PACKS:
        combined = "\n".join(
            [
                (pack / "README.md").read_text(encoding="utf-8"),
                (pack / "sample-command.md").read_text(encoding="utf-8"),
                (pack / "expected-exceptions.md").read_text(encoding="utf-8"),
            ],
        ).lower()
        assert "export-based" in combined
        assert "reconforge rules validate" in combined
        assert "reconforge rules run" in combined
        assert "expected exceptions" in combined
