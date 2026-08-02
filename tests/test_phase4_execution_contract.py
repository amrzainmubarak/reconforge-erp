from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
BACKLOG_PATH = ROOT / "docs" / "execution" / "BACKLOG.yaml"


def _backlog() -> dict[str, Any]:
    loaded = yaml.safe_load(BACKLOG_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_phase4_goal_covers_all_seven_workstreams_without_relabeling_old_closure() -> None:
    backlog = _backlog()
    tasks = backlog["tasks"]
    phase4 = [task for task in tasks if task["id"].startswith("P4-")]

    assert backlog["phase"] == "Phase 4 — Global Capability Expansion"
    assert {task["goal_workstream"] for task in phase4} == {
        "deep_close_and_consolidation",
        "advanced_matching",
        "live_connectors_and_writeback",
        "high_volume_concurrency",
        "high_availability_and_disaster_recovery",
        "enterprise_identity_and_policy",
        "coherent_platform_breadth",
    }
    assert [task["id"] for task in phase4] == [
        "P4-FIN-001",
        "P4-FIN-002",
        "P4-MAT-001",
        "P4-CON-001",
        "P4-SCL-001",
        "P4-REL-001",
        "P4-IAM-001",
        "P4-PLAT-001",
    ]
    assert phase4[0]["status"] == "completed"
    assert phase4[1]["status"] == "in_progress"
    assert phase4[2]["status"] == "in_progress"
    assert phase4[3]["status"] == "in_progress"
    assert phase4[4]["status"] == "in_progress"
    assert phase4[5]["status"] == "in_progress"
    assert all(task["status"] == "planned" for task in phase4[6:])


def test_phase4_dependencies_exist_and_final_breadth_waits_for_every_workstream() -> None:
    tasks = _backlog()["tasks"]
    by_id = {task["id"]: task for task in tasks}
    phase4 = [task for task in tasks if task["id"].startswith("P4-")]

    assert len(by_id) == len(tasks)
    assert all(dependency in by_id for task in phase4 for dependency in task["depends_on"])
    assert set(by_id["P4-PLAT-001"]["depends_on"]) == {
        "P4-FIN-002",
        "P4-MAT-001",
        "P4-CON-001",
        "P4-SCL-001",
        "P4-REL-001",
        "P4-IAM-001",
    }


def test_phase4_does_not_claim_unfinished_global_superiority() -> None:
    tasks = _backlog()["tasks"]
    phase4 = [task for task in tasks if task["id"].startswith("P4-")]
    forbidden = ("best globally", "enterprise-ready", "compliant", "certified")

    assert any(task["status"] != "completed" for task in phase4)
    for task in phase4:
        evidence = str(task["exit_evidence"]).casefold()
        assert all(claim not in evidence for claim in forbidden)
