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


def test_phase_gates_have_evidence_and_external_gates_fail_closed() -> None:
    matrix = _load_mapping(MATRIX_PATH)
    phase_gate_by_id = {
        gate["id"]: gate for phase in matrix["phases"] for gate in phase["required_gates"]
    }
    assert phase_gate_by_id
    assert all(str(gate["evidence"]).strip() for gate in phase_gate_by_id.values())

    policy = matrix["external_gate_policy"]
    for gate in policy["gates"]:
        assert gate["id"] in phase_gate_by_id
        assert phase_gate_by_id[gate["id"]].get("external") is True
        assert gate["status"] in policy["allowed_statuses"]
        if gate["status"] == "verified":
            assert gate["evidence_artifacts"]
        else:
            assert gate["evidence_artifacts"] == []


def test_phase_three_has_no_unsupported_completion_shortcut() -> None:
    matrix = _load_mapping(MATRIX_PATH)
    closure = matrix["closure_policy"]
    assert closure["all_tasks_completed"] is True
    assert closure["all_required_gates_verified"] is True
    assert closure["external_evidence_may_not_be_simulated"] is True
    assert {
        "universal_superiority",
        "enterprise_ready",
        "compliant",
        "certified",
        "unsupported_scale",
        "unverified_customer_validation",
    }.issubset(closure["unsupported_claims_forbidden"])
