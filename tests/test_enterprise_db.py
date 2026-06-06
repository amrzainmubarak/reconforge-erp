from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.db import connect, database_status, run_migrations
from reconforge.domain.repositories import PeriodRepository, WorkspaceRepository

runner = CliRunner()


def test_db_init_creates_expected_schema_and_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "reconforge.db"

    first = run_migrations(db_path)
    second = run_migrations(db_path)

    assert first.current_version == 2
    assert first.applied_versions == [1, 2]
    assert second.current_version == 2
    assert second.applied_versions == []

    connection = connect(db_path, require_exists=True)
    try:
        tables = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
    finally:
        connection.close()

    assert {
        "schema_migrations",
        "workspaces",
        "periods",
        "users",
        "roles",
        "permissions",
        "reconciliations",
        "role_permissions",
        "evidence_objects",
        "workflow_transitions",
        "audit_events",
        "audit_ledger_state",
    } <= tables


def test_db_status_reports_pending_and_current_versions(tmp_path: Path) -> None:
    db_path = tmp_path / "status.sqlite"
    run_migrations(db_path)

    status = database_status(db_path)

    assert status.current_version == 2
    assert status.latest_version == 2
    assert status.pending_versions == []


def test_domain_repositories_create_workspace_and_period(tmp_path: Path) -> None:
    db_path = tmp_path / "domain.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        workspace_repo = WorkspaceRepository(connection)
        period_repo = PeriodRepository(connection)
        workspace = workspace_repo.create(name="Pilot Workspace")
        period = period_repo.create(
            workspace_id=workspace.id,
            name="2026-05",
            start_date="2026-05-01",
            end_date="2026-05-31",
        )

        assert workspace_repo.get(workspace.id) == workspace
        assert period_repo.get(period.id) == period
        assert period_repo.list(workspace_id=workspace.id) == [period]
    finally:
        connection.close()


def test_db_cli_init_migrate_status(tmp_path: Path) -> None:
    db_path = tmp_path / "cli.db"

    init = runner.invoke(app, ["db", "init", "--db", str(db_path)])
    migrate = runner.invoke(app, ["db", "migrate", "--db", str(db_path)])
    status = runner.invoke(app, ["db", "status", "--db", str(db_path)])

    assert init.exit_code == 0
    assert "Database ready" in init.output
    assert migrate.exit_code == 0
    assert "Applied now: none" in migrate.output
    assert status.exit_code == 0
    assert "Current version" in status.output
    assert "Traceback" not in init.output + migrate.output + status.output


def test_db_cli_rejects_traversal_path_without_traceback() -> None:
    result = runner.invoke(app, ["db", "init", "--db", "output/../unsafe.db"])

    assert result.exit_code == 1
    assert "Unsafe database path" in result.output
    assert "Traceback" not in result.output


def test_db_cli_handles_malformed_db_without_traceback(tmp_path: Path) -> None:
    db_path = tmp_path / "malformed.db"
    db_path.write_text("not a sqlite database", encoding="utf-8")

    result = runner.invoke(app, ["db", "status", "--db", str(db_path)])

    assert result.exit_code == 1
    assert "Unable to read ReconForge database" in result.output
    assert "Traceback" not in result.output
