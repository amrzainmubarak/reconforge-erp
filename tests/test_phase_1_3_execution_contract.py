from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "docs" / "execution" / "PHASE_1_3_EXECUTION_MATRIX.yaml"
BACKLOG_PATH = ROOT / "docs" / "execution" / "BACKLOG.yaml"


def _load_mapping(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_phase_matrix_closes_every_post_baseline_backlog_task_once() -> None:
    matrix = _load_mapping(MATRIX_PATH)
    backlog = _load_mapping(BACKLOG_PATH)
    tasks = backlog["tasks"]
    task_ids = [task["id"] for task in tasks]
    assert len(task_ids) == len(set(task_ids))

    expected = {task_id for task_id in task_ids if not task_id.startswith("P0-")}
    mapped = [task_id for phase in matrix["phases"] for task_id in phase["task_ids"]]
    assert len(mapped) == len(set(mapped))
    assert set(mapped) == expected


def test_backlog_dependencies_are_closed_and_phase_ordered() -> None:
    matrix = _load_mapping(MATRIX_PATH)
    tasks = _load_mapping(BACKLOG_PATH)["tasks"]
    task_by_id = {task["id"]: task for task in tasks}
    order = {
        task_id: phase_index
        for phase_index, phase in enumerate(matrix["phases"], start=1)
        for task_id in phase["task_ids"]
    }
    for task in tasks:
        for dependency in task["depends_on"]:
            assert dependency in task_by_id
            if task["id"] in order and dependency in order:
                assert order[dependency] <= order[task["id"]]


def test_required_tasks_are_complete_and_optional_assurance_is_non_blocking() -> None:
    matrix = _load_mapping(MATRIX_PATH)
    backlog = _load_mapping(BACKLOG_PATH)
    tasks = backlog["tasks"]
    assert set(backlog["status_values"]) == {"planned", "in_progress", "blocked", "deferred", "completed"}
    assert set(backlog["release_requirement_values"]) == {"required", "optional_assurance"}
    assert all(task["status"] in backlog["status_values"] for task in tasks)
    assert all(task.get("release_requirement", "required") in backlog["release_requirement_values"] for task in tasks)

    required = [task for task in tasks if task.get("release_requirement", "required") == "required"]
    required_non_p0 = [task for task in required if not task["id"].startswith("P0-")]
    optional = [task for task in tasks if task.get("release_requirement") == "optional_assurance"]

    assert required
    assert all(task["status"] == "completed" for task in required)
    assert len(required_non_p0) == 41
    assert {task["id"] for task in optional} == {"P3-EXT-001", "P3-EXT-002"}
    assert all(task["status"] == "deferred" for task in optional)
    assert matrix["closure_policy"]["optional_assurance_items_block_release"] is False


def test_phase_gates_have_evidence_and_optional_assurance_fails_closed() -> None:
    matrix = _load_mapping(MATRIX_PATH)
    phase_gate_by_id = {
        gate["id"]: gate for phase in matrix["phases"] for gate in phase["required_gates"]
    }
    assert phase_gate_by_id
    assert all(str(gate["evidence"]).strip() for gate in phase_gate_by_id.values())

    policy = matrix["optional_assurance_policy"]
    assert policy["release_blocking"] is False
    for gate in policy["gates"]:
        assert gate["id"] not in phase_gate_by_id
        assert gate["status"] in policy["allowed_statuses"]
        if gate["status"] == "verified":
            assert gate["evidence_artifacts"]
        else:
            assert gate["evidence_artifacts"] == []


def test_owner_team_closure_preserves_claim_and_external_evidence_boundaries() -> None:
    matrix = _load_mapping(MATRIX_PATH)
    closure = matrix["closure_policy"]
    assert closure["all_required_tasks_completed"] is True
    assert closure["all_required_gates_verified"] is True
    assert closure["owner_team_release_authority"] is True
    assert closure["optional_assurance_items_block_release"] is False
    assert closure["external_evidence_may_not_be_simulated"] is True
    assert {
        "universal_superiority",
        "enterprise_ready",
        "compliant",
        "certified",
        "unsupported_scale",
        "unverified_customer_validation",
    }.issubset(closure["unsupported_claims_forbidden"])
