from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import yaml

from reconforge.infrastructure.postgres_operations import POSTGRES_MIGRATION_REVISIONS

ROOT = Path(__file__).resolve().parents[1]


def _yaml(relative: str) -> dict[str, Any]:
    value = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _test_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    }


def test_exit_audit_has_complete_evidence_and_claim_boundaries() -> None:
    audit = _yaml("docs/execution/P3_ENT_004_EXIT_AUDIT.yaml")
    assert audit["task_id"] == "P3-ENT-004"
    assert audit["status"] == "verified"
    assert audit["migration_head"] == "0046_postgres_scope_authority"
    assert audit["migration_head"] in POSTGRES_MIGRATION_REVISIONS
    assert {gate["id"] for gate in audit["gates"]} == {
        "hierarchical_transaction_scope",
        "background_job_scope",
        "authorized_export_scope",
        "object_storage_scope",
        "business_domain_rls",
        "durable_api_scope_authority",
        "hostile_failure_paths",
        "migration_and_recovery",
    }
    assert all(gate["status"] == "verified" and gate["evidence"] for gate in audit["gates"])
    assert all((ROOT / item).is_file() for gate in audit["gates"] for item in gate["evidence"])
    assert {
        "no_ha_or_dr_claim",
        "no_compliance_or_certification_claim",
        "no_external_penetration_or_assurance_claim",
        "no_enterprise_ready_claim",
    }.issubset(audit["limitations"])
    assert not any(audit["publication"].values())
    runtime = audit["runtime_evidence"]
    assert runtime["consolidated_live_result"] == "63_passed"
    assert runtime["consolidated_live_skips"] == 0
    assert runtime["direct_rollback"] == "0046_to_0045_to_0046_passed"
    assert runtime["long_rollback"] == "0046_to_0011_to_0046_passed"
    assert runtime["live_policy_count"] == runtime["live_rls_table_count"] == runtime[
        "live_forced_rls_table_count"
    ]


def test_failure_matrix_names_real_tests_and_covers_required_surfaces() -> None:
    audit = _yaml("docs/execution/P3_ENT_004_EXIT_AUDIT.yaml")
    all_tests: set[str] = set()
    for path in (ROOT / "tests").glob("test_*.py"):
        all_tests.update(_test_functions(path))
    entries = audit["failure_matrix"]
    assert len(entries) == 14
    assert all(entry["evidence_test"] in all_tests for entry in entries)
    threats = {entry["threat"] for entry in entries}
    assert any("job" in threat for threat in threats)
    assert any("export" in threat for threat in threats)
    assert any("object" in threat for threat in threats)
    assert any("api" in threat for threat in threats)
    assert any("tenant" in threat for threat in threats)
    assert all(entry["result"] not in {"allowed", "unknown", "planned"} for entry in entries)


def test_catalog_inventory_classifies_every_remaining_tenant_global_policy() -> None:
    inventory = _yaml("docs/execution/POSTGRES_SCOPE_INVENTORY.yaml")
    classifications = inventory["remaining_tenant_only_classification"]
    classified = [
        table
        for group in classifications.values()
        for table in group
    ]
    assert len(classified) == len(set(classified)) == inventory["counts"][
        "tenant_only_policies_without_parent_resolution"
    ]
    assert classifications["missing_authoritative_workspace_attribution_requires_schema_evolution"] == []


def test_every_postgres_business_boundary_uses_trusted_execution_scope() -> None:
    for relative in (
        "reconforge/api/server_reconciliation.py",
        "reconforge/api/server_evidence.py",
        "reconforge/api/server_master_data.py",
        "reconforge/api/server_ledger.py",
        "reconforge/api/server_close.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "request_execution_scope(request)" in source
        assert "workspace_id=scope.workspace_id" in source
        assert "legal_entity_id=scope.legal_entity_id" in source
