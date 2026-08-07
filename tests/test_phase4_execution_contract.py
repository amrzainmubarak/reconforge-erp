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
    assert phase4[6]["status"] == "in_progress"
    assert phase4[7]["status"] == "in_progress"


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


def test_server_boundaries_installs_all_locked_extras_for_live_matrix() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["server-boundaries"]["steps"]
    install_commands = [str(step.get("run", "")) for step in steps if step.get("name") == "Install locked server dependencies"]
    assert install_commands == ["uv sync --locked --all-extras --no-editable --python 3.12"]


def test_test_matrix_verifies_optional_imports_after_all_extra_sync() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["test"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    install_index = names.index("Install locked dependencies")
    verify_index = names.index("Verify optional test dependency surface")
    assert install_index < verify_index
    command = str(steps[verify_index]["run"])
    assert "uv run --no-sync python -c" in command
    for module in ("cbor2", "cryptography", "opentelemetry.sdk"):
        assert module in command


def test_test_matrix_verifies_checked_in_benchmark_evidence_before_collection() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["test"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    verify_index = names.index("Verify checked-in benchmark evidence index")
    pytest_index = names.index("Pytest")
    assert verify_index < pytest_index
    assert str(steps[verify_index]["run"]) == (
        "uv run --no-sync python .github/scripts/verify_benchmark_index.py --root ."
    )


def test_server_boundaries_bootstraps_versioned_postgres_native_tools_before_live_tests() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["server-boundaries"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    native_index = names.index("Install PostgreSQL native client tools")
    dependency_index = names.index("Install locked server dependencies")
    assert native_index < dependency_index
    native_run = str(steps[native_index]["run"])
    assert "sudo apt-get install --no-install-recommends -y postgresql-client" in native_run
    assert "pg_config --bindir" in native_run
    for tool in ("pg_dump", "pg_restore", "createdb", "dropdb", "psql"):
        assert f'test -x "$(pg_config --bindir)/{tool}"' in native_run
