from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import reconforge.db.backup as backup_module
import reconforge.db.migrations as migration_module
from reconforge.api.security import create_session
from reconforge.audit import list_audit_events
from reconforge.auth import LocalAuthService
from reconforge.cli import app
from reconforge.db import connect, database_status, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.db.exporter import DBBridgeError, checksum_file
from reconforge.domain.repositories import WorkspaceRepository
from reconforge.platform.master_data import MasterDataService

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
    assert manifest["schema_version"] == migration_module.MIGRATIONS[-1].version
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


def test_backup_restore_preserves_version_seven_master_data(tmp_path: Path) -> None:
    source_db = _seed_db(tmp_path)
    connection = connect(source_db, require_exists=True)
    try:
        service = MasterDataService(connection)
        service.upsert_organization(organization_code="SYN", name="Synthetic Group")
        service.upsert_organization(organization_code="SYN2", name="Synthetic Group Two")
        service.upsert_legal_entity(
            organization_code="SYN",
            entity_code="EG01",
            name="Synthetic Egypt",
            currency_code="EGP",
        )
        service.upsert_branch(
            organization_code="SYN",
            branch_code="CAI",
            name="Cairo",
            entity_code="EG01",
        )
        service.upsert_period(name="2026-07", start_date="2026-07-01", end_date="2026-07-31")
    finally:
        connection.close()

    backup = create_backup(source_db, tmp_path / "master-data-backup")
    restored_db = tmp_path / "master-data-restored.db"
    restore_backup(restored_db, backup.backup_path)

    connection = connect(restored_db, require_exists=True)
    try:
        snapshot = MasterDataService(connection).snapshot()
        assert snapshot["summary"] == {
            "workspace": "default",
            "organizations": 2,
            "legal_entities": 1,
            "branches": 1,
            "periods": 1,
            "active_currencies": 6,
        }
        assert {row["organization_code"] for row in snapshot["organizations"]} == {"SYN", "SYN2"}
        assert snapshot["branches"][0]["branch_code"] == "CAI"
    finally:
        connection.close()


def test_version_six_backup_restores_then_upgrades_to_latest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_migrations = migration_module.MIGRATIONS
    monkeypatch.setattr(migration_module, "MIGRATIONS", full_migrations[:6])
    monkeypatch.setattr(backup_module, "MIGRATIONS", full_migrations[:6])
    source_db = tmp_path / "version-six.db"
    migration_module.run_migrations(source_db)
    connection = connect(source_db, require_exists=True)
    try:
        connection.execute(
            "INSERT INTO workspaces (id, name, local_first_note, created_at) VALUES (?, ?, ?, ?)",
            ("WS-v6", "Version Six", "Local", "2026-01-01T00:00:00Z"),
        )
        connection.executemany(
            "INSERT INTO organizations (id, workspace_id, name, created_at) VALUES (?, ?, ?, ?)",
            [
                ("ORG-v6-a", "WS-v6", "Legacy One", "2026-01-01T00:00:00Z"),
                ("ORG-v6-b", "WS-v6", "Legacy Two", "2026-01-01T00:00:00Z"),
            ],
        )
        connection.execute(
            """
            INSERT INTO legal_entities (id, organization_id, entity_code, name, currency, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("LE-v6", "ORG-v6-a", "EG01", "Legacy Egypt", "egp", "2026-01-01T00:00:00Z"),
        )
        connection.execute(
            """
            INSERT INTO periods (id, workspace_id, name, start_date, end_date, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("PER-v6", "WS-v6", "2026-01", "2026-01-01", "2026-01-31", "Open", "2026-01-01T00:00:00Z"),
        )
        connection.commit()
    finally:
        connection.close()

    backup = backup_module.create_backup(source_db, tmp_path / "version-six-backup")
    assert backup.schema_version == 6
    monkeypatch.setattr(migration_module, "MIGRATIONS", full_migrations)
    monkeypatch.setattr(backup_module, "MIGRATIONS", full_migrations)

    restored_db = tmp_path / "version-six-restored.db"
    backup_module.restore_backup(restored_db, backup.backup_path)
    status = database_status(restored_db)
    assert status.current_version == status.latest_version == migration_module.MIGRATIONS[-1].version
    assert status.pending_versions == []

    connection = connect(restored_db, require_exists=True)
    try:
        organization_codes = {
            str(row["organization_code"])
            for row in connection.execute("SELECT organization_code FROM organizations").fetchall()
        }
        currency = connection.execute("SELECT code FROM currencies WHERE code = 'EGP'").fetchone()
        period = connection.execute("SELECT fiscal_year, period_number FROM periods WHERE id = 'PER-v6'").fetchone()
        assert len(organization_codes) == 2
        assert all(code.startswith("LEGACY-") for code in organization_codes)
        assert currency is not None
        assert period is not None
        assert (period["fiscal_year"], period["period_number"]) == (2026, 1)
    finally:
        connection.close()


def test_restore_fills_optional_missing_restore_columns_from_defaults(tmp_path: Path) -> None:
    source_db = _seed_db(tmp_path)
    connection = connect(source_db, require_exists=True)
    try:
        workspace_id = str(connection.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"])
        organization_id = "ORG-legacy-missing"
        legal_entity_id = "LE-legacy-missing"
        period_id = "PER-legacy-missing"
        connection.execute(
            """
            INSERT INTO organizations (
                id, workspace_id, name, created_at, organization_code, active, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                organization_id,
                workspace_id,
                "Legacy Organization",
                "2026-01-01T00:00:00Z",
                "ORGOLD",
                0,
                "2026-01-01T00:00:00Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO legal_entities (
                id, organization_id, entity_code, name, currency, created_at, active, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                legal_entity_id,
                organization_id,
                "LEG1",
                "Legacy Entity",
                "EGP",
                "2026-01-02T00:00:00Z",
                0,
                "2026-01-02T00:00:00Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO periods (
                id, workspace_id, name, start_date, end_date, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                period_id,
                workspace_id,
                "2026-01",
                "2026-01-01",
                "2026-01-31",
                "Open",
                "2026-01-03T00:00:00Z",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    original_backup = create_backup(source_db, tmp_path / "mutated-input")
    backup_payload = json.loads(original_backup.backup_path.read_text(encoding="utf-8"))
    tables = backup_payload["tables"]
    assert isinstance(tables, dict)

    def strip_optional_columns(rows: list[object], row_id: str, columns: set[str]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for row in rows:
            normalized_row = dict(row)
            if str(normalized_row.get("id", "")) == row_id:
                for column in columns:
                    normalized_row.pop(column, None)
            normalized.append(normalized_row)
        return normalized

    tables["organizations"] = strip_optional_columns(
        list(tables.get("organizations", [])),
        organization_id,
        {"organization_code", "active", "updated_at"},
    )
    tables["legal_entities"] = strip_optional_columns(
        list(tables.get("legal_entities", [])),
        legal_entity_id,
        {"active", "updated_at"},
    )
    tables["periods"] = strip_optional_columns(
        list(tables.get("periods", [])),
        period_id,
        {"fiscal_year", "period_number", "status_reason", "updated_at"},
    )

    mutated_backup_dir = tmp_path / "restorable-missing-defaults"
    mutated_backup_dir.mkdir()
    mutated_backup_path = mutated_backup_dir / "backup.json"
    mutated_manifest_path = mutated_backup_dir / "manifest.json"

    with mutated_backup_path.open("w", encoding="utf-8") as handle:
        json.dump(backup_payload, handle, ensure_ascii=False, indent=2)

    manifest = json.loads(original_backup.manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["backup.json"]["sha256"] = checksum_file(mutated_backup_path)
    manifest["artifacts"]["backup.json"]["bytes"] = mutated_backup_path.stat().st_size
    with mutated_manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    restored_db = tmp_path / "mutated-restore.db"
    restore_backup(restored_db, mutated_backup_dir)

    restored = connect(restored_db, require_exists=True)
    try:
        restored_organization = restored.execute(
            "SELECT organization_code, active, created_at, updated_at FROM organizations WHERE id = ?",
            (organization_id,),
        ).fetchone()
        restored_legal_entity = restored.execute(
            "SELECT active, created_at, updated_at FROM legal_entities WHERE id = ?",
            (legal_entity_id,),
        ).fetchone()
        restored_period = restored.execute(
            "SELECT fiscal_year, period_number, status_reason, created_at, updated_at FROM periods WHERE id = ?",
            (period_id,),
        ).fetchone()

        assert restored_organization is not None
        assert restored_legal_entity is not None
        assert restored_period is not None
        assert str(restored_organization["organization_code"]).startswith("LEGACY-")
        assert restored_organization["active"] == 1
        assert restored_organization["updated_at"] == restored_organization["created_at"]
        assert restored_legal_entity["active"] == 1
        assert restored_legal_entity["updated_at"] == restored_legal_entity["created_at"]
        assert restored_period["fiscal_year"] == 2026
        assert restored_period["period_number"] == 1
        assert restored_period["status_reason"] == ""
        assert restored_period["updated_at"] == restored_period["created_at"]
    finally:
        restored.close()


def test_insert_rows_delegates_exact_fractional_default_to_sqlite() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    try:
        connection.execute(
            """
            CREATE TABLE account_reconciliation_templates (
                id TEXT PRIMARY KEY,
                materiality_threshold_decimal TEXT NOT NULL
                    DEFAULT '0.123456789012345678901234567890'
            )
            """,
        )

        backup_module._insert_rows(
            connection,
            table="account_reconciliation_templates",
            rows=[{"id": "T-EXACT-DEFAULT"}],
        )

        restored = connection.execute(
            "SELECT materiality_threshold_decimal, typeof(materiality_threshold_decimal) AS value_type "
            "FROM account_reconciliation_templates WHERE id = ?",
            ("T-EXACT-DEFAULT",),
        ).fetchone()
        assert restored is not None
        assert restored["materiality_threshold_decimal"] == "0.123456789012345678901234567890"
        assert restored["value_type"] == "text"
        insert_statement = next(
            statement
            for statement in statements
            if statement.lstrip().upper().startswith("INSERT INTO")
        )
        assert "materiality_threshold_decimal" not in insert_statement
    finally:
        connection.close()


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
