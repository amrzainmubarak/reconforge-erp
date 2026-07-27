from __future__ import annotations

import json
from pathlib import Path


def test_workflow_schema_files_are_valid_json() -> None:
    schema_dir = Path("docs/schemas")
    required = {
        "close_checklist.schema.json",
        "certification_metadata.schema.json",
        "variance_report.schema.json",
        "anonymization_manifest.schema.json",
        "management_pack.schema.json",
        "synthetic_generator_manifest.schema.json",
        "rule_results.schema.json",
        "period_comparison.schema.json",
        "client_pack_manifest.schema.json",
        "evidence_index.schema.json",
        "security_architecture.schema.json",
        "threat_model_index.schema.json",
        "asvs_mapping.schema.json",
        "ssdf_mapping.schema.json",
        "slsa_provenance_plan.schema.json",
        "release_manifest.schema.json",
        "sbom_manifest.schema.json",
        "supply_chain_policy.schema.json",
        "supply_chain_exceptions.schema.json",
        "golden_finance_dataset_registry.schema.json",
        "engine_parity_matrix.schema.json",
        "risk_register.schema.json",
        "maturity_policy.schema.json",
        "file_ingestion_inventory.schema.json",
        "control_matrix.schema.json",
        "profile_template.schema.json",
    }
    assert {path.name for path in schema_dir.glob("*.schema.json")} >= required
    for filename in required:
        payload = json.loads((schema_dir / filename).read_text(encoding="utf-8"))
        assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert payload["type"] == "object"


def test_close_schema_documents_expected_statuses() -> None:
    payload = json.loads(Path("docs/schemas/close_checklist.schema.json").read_text(encoding="utf-8"))
    status_enum = payload["properties"]["tasks"]["items"]["properties"]["status"]["enum"]
    assert status_enum == ["Not Started", "In Progress", "Blocked", "Complete", "Not Applicable"]


def test_certification_schema_documents_expected_statuses() -> None:
    payload = json.loads(Path("docs/schemas/certification_metadata.schema.json").read_text(encoding="utf-8"))
    assert payload["properties"]["certification_status"]["enum"] == [
        "Draft",
        "Prepared",
        "Reviewed",
        "Accepted Risk",
        "Needs Follow-up",
    ]
