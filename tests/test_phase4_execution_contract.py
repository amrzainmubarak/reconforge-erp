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
    assert "sudo apt-get install --no-install-recommends -y libpq-dev postgresql-client-16" in native_run
    assert "set -euo pipefail" in native_run
    assert "python .github/scripts/verify_postgres_native_tools.py --expected-major 16 --print-bindir" in native_run
    assert 'printf \'%s\\n\' "$native_bindir" >> "$GITHUB_PATH"' in native_run


def test_native_tool_verifier_is_packaged_and_executable_from_workflow() -> None:
    script = ROOT / ".github" / "scripts" / "verify_postgres_native_tools.py"
    assert script.is_file()
    source = script.read_text(encoding="utf-8")
    assert "shell=False" in source
    assert "_REQUIRED_TOOLS" in source
    assert "--expected-major" in source


def test_server_boundaries_matrix_retains_the_repaired_postgres_failure_surfaces() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    inventory = yaml.safe_load((ROOT / "docs" / "execution" / "POSTGRES_PARITY_INVENTORY.yaml").read_text(encoding="utf-8"))
    tests = {str(boundary.get("test")) for boundary in inventory["boundaries"] if boundary.get("test")}
    assert {"tests/test_postgres_backup.py", "tests/test_application_metrics.py"}.issubset(tests)

    job = workflow["jobs"]["server-boundaries"]
    live_step = next(step for step in job["steps"] if step.get("name") == "Run live server-boundary tests")
    env = live_step["env"]
    assert env["PGSERVICEFILE"] == "${{ runner.temp }}/reconforge-pgservice.conf"
    assert env["RECONFORGE_TEST_POSTGRES_SOURCE_SERVICE"] == "reconforge_ci_source"
    assert env["RECONFORGE_TEST_POSTGRES_MAINTENANCE_SERVICE"] == "reconforge_ci_admin"
    run = str(live_step["run"])
    assert "mapfile -t parity_tests" in run
    assert 'pytest "${parity_tests[@]}"' in run
    assert "tests/test_alembic_postgres.py" in run
    assert "tests/test_postgres_grouped_matching_runtime.py" in run
    assert "test_live_postgres_grouped_matching_worker_persists_group_lineage_and_is_tenant_scoped" in run
    assert "test_live_postgres_persistent_scheduler_coordinates_spawned_processes" in run
    assert "test_live_postgres_worker_crash_after_checkpoint_resumes_without_duplicate_effect" in run
    assert "test_live_postgres_worker_database_fault_after_checkpoint_resumes_without_duplicate_effect" in run
    assert "uv run --no-sync pytest tests/test_api_operations.py -q" in run
    assert "uv run --no-sync pytest tests/test_api_metrics.py -q" in run
    assert "uv run --no-sync pytest tests/test_postgres_backup.py -k 'test_live_postgres_native_adapter_encrypted_backup_isolated_restore_and_cleanup' -q" in run
    assert "uv run --no-sync pytest tests/test_application_metrics.py -k 'test_live_postgres_metrics_and_sqlite_parity' -q" in run
    assert "uv run --no-sync pytest tests/test_scoped_exports.py -k 'test_live_scoped_export_excludes_sibling_workspace_and_entity' -q" in run
    assert "uv run --no-sync pytest tests/test_api_server_scoped_exports.py -k 'test_live_server_scoped_export_http_is_service_scoped_and_tenant_isolated' -q" in run
    assert "uv run --no-sync pytest tests/test_postgres_manufacturing_cost_control.py -q" in run
    assert "uv run --no-sync pytest tests/test_api_server_manufacturing_cost_control.py -q" in run
    assert "uv run --no-sync pytest tests/test_postgres_consolidation_close.py -k 'test_live_postgres_consolidation_close_is_tenant_isolated_and_replayable' -q" in run
    assert "uv run --no-sync pytest tests/test_postgres_federation.py -k 'test_live_postgres_federation_replay_link_session_and_rls' -q" in run
    assert "uv run --no-sync pytest tests/test_postgres_bank_statement.py -q" in run
    assert "uv run --no-sync pytest tests/test_api_server_bank_statement.py -q" in run
    assert "pg_dump --format=custom" in run
    assert "pg_restore --list" in run
    assert "test -s \"$native_smoke_dump\"" in run
