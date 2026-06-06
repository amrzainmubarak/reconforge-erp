from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reconforge.api.security import create_session
from reconforge.audit import list_audit_events
from reconforge.auth import LocalAuthService
from reconforge.cli import app
from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.db.exporter import DBBridgeError, checksum_file
from reconforge.domain.repositories import WorkspaceRepository

runner = CliRunner()


def _seed_db(tmp_path: Path, *, name: str = "Source Workspace") -> Path:
    db_path = tmp_path / f"{name.lower().replace(' ', '_')}.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        WorkspaceRepository(connection).create(name=name)
        auth = LocalAuthService(connection)
        user = auth.init_admin(username=f"admin_{name.lower().split()[0]}", password="Secret-123")
        create_session(connection, user=user)
    finally:
        connection.close()
    return db_path


def _workspace_names(db_path: Path) -> set[str]:
    connection = connect(db_path, require_exists=True)
    try:
        return {str(row["name"]) for row in connection.execute("SELECT name FROM workspaces").fetchall()}
    finally:
        connection.close()


def _audit_actions(db_path: Path) -> list[str]:
    connection = connect(db_path, require_exists=True)
    try:
        return [event.action for event in list_audit_events(connection)]
    finally:
        connection.close()


def test_backup_writes_manifest_checksum_and_audit_event(tmp_path: Path) -> None:
    db_path = _seed_db(tmp_path)

    result = create_backup(db_path, tmp_path / "backups")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    backup = json.loads(result.backup_path.read_text(encoding="utf-8"))

    assert result.backup_path.exists()
    assert result.manifest_path.exists()
    assert manifest["artifacts"]["backup.json"]["sha256"] == checksum_file(result.backup_path)
    assert manifest["schema_version"] == 6
    assert "sensitive local business data" in manifest["privacy_warning"]
    assert "credential verifier" in backup["restore_sensitive_material"]
    assert "api_sessions" in backup["excluded_tables"]
    assert "api_sessions" not in backup["tables"]
    assert "db_backup_created" in _audit_actions(db_path)


def test_restore_validates_backup_checksum(tmp_path: Path) -> None:
    db_path = _seed_db(tmp_path)
    result = create_backup(db_path, tmp_path / "backups")
    result.backup_path.write_text(result.backup_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(DBBridgeError, match="checksum"):
        restore_backup(tmp_path / "restored.db", result.backup_path)


def test_restore_refuses_existing_db_without_force(tmp_path: Path) -> None:
    source_db = _seed_db(tmp_path)
    target_db = _seed_db(tmp_path, name="Target Workspace")
    result = create_backup(source_db, tmp_path / "backups")

    with pytest.raises(DBBridgeError, match="--force"):
        restore_backup(target_db, result.backup_path)


def test_restore_with_force_replaces_target_and_writes_audit_event(tmp_path: Path) -> None:
    source_db = _seed_db(tmp_path, name="Source Workspace")
    target_db = _seed_db(tmp_path, name="Target Workspace")
    result = create_backup(source_db, tmp_path / "backups")

    restore = restore_backup(target_db, result.backup_path, force=True)

    assert restore.db_path == target_db.resolve()
    assert "Source Workspace" in _workspace_names(target_db)
    assert "Target Workspace" not in _workspace_names(target_db)
    assert "db_backup_created" in _audit_actions(target_db)
    assert "db_backup_restored" in _audit_actions(target_db)


def test_bad_backup_cli_error_is_sanitized(tmp_path: Path) -> None:
    bad_dir = tmp_path / "bad_backup"
    bad_dir.mkdir()
    (bad_dir / "backup.json").write_text("{bad json", encoding="utf-8")
    (bad_dir / "manifest.json").write_text(json.dumps({"artifacts": {"backup.json": {"sha256": "bad"}}}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "db",
            "restore",
            "--db",
            str(tmp_path / "restored.db"),
            "--input",
            str(bad_dir / "backup.json"),
        ],
    )

    assert result.exit_code == 1
    assert "Backup JSON could not be parsed" in result.output or "Backup checksum verification failed" in result.output
    assert "Traceback" not in result.output
