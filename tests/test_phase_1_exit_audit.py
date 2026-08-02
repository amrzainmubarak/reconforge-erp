from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load(relative: str) -> dict[str, Any]:
    value = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_phase_one_exit_audit_matches_normative_matrix_and_completed_tasks() -> None:
    audit = _load("docs/execution/PHASE_1_EXIT_AUDIT.yaml")
    matrix = _load("docs/execution/PHASE_1_3_EXECUTION_MATRIX.yaml")
    backlog = _load("docs/execution/BACKLOG.yaml")
    phase = next(item for item in matrix["phases"] if item["id"] == "phase_1")
    tasks = {item["id"]: item for item in backlog["tasks"]}

    assert audit["status"] == "verified"
    assert audit["task_ids"] == phase["task_ids"]
    assert all(tasks[task_id]["status"] == "completed" for task_id in audit["task_ids"])
    assert {gate["id"] for gate in audit["gates"]} == {gate["id"] for gate in phase["required_gates"]}
    assert all(gate["status"] == "verified" and gate["evidence"] for gate in audit["gates"])


def test_phase_one_backend_and_recovery_evidence_is_current_and_bounded() -> None:
    audit = _load("docs/execution/PHASE_1_EXIT_AUDIT.yaml")
    boundaries = _load("docs/execution/REPOSITORY_BOUNDARY_INVENTORY.yaml")
    postgres = _load("docs/execution/POSTGRES_PARITY_INVENTORY.yaml")
    recovery = _load("docs/operations/backup-restore-matrix.v1.yaml")

    assert boundaries["summary"]["backend_neutral_application"] == len(boundaries["application_services"])
    assert boundaries["summary"]["direct_sqlite"] == 0
    assert boundaries["summary"]["partial_repository"] == 0
    assert postgres["current_live_gate"]["covered_live_boundaries"] == 23
    assert postgres["current_live_gate"]["skipped_live_boundaries"] == 0
    cells = {cell["id"]: cell for cell in recovery["cells"]}
    assert cells["community-sqlite-v6-to-v24"]["status"] == "verified"
    assert cells["community-sqlite-v24-to-v24"]["status"] == "verified"
    assert cells["team-postgresql-17-current"]["status"] == "verified"
    assert cells["enterprise-postgresql-ha"]["status"] == "planned"
    assert cells["regulated-airgap-postgresql"]["status"] == "planned"
    assert "enterprise_ha_is_phase_3" in audit["limitations"]
    assert "no_production_readiness_claim" in audit["limitations"]


def test_phase_one_exit_audit_file_evidence_exists() -> None:
    audit = _load("docs/execution/PHASE_1_EXIT_AUDIT.yaml")
    paths = [item for gate in audit["gates"] for item in gate["evidence"] if "/" in item]
    assert paths
    assert all((ROOT / path).is_file() for path in paths)
