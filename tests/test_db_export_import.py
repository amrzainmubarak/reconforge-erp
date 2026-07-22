from __future__ import annotations

import json
from pathlib import Path

from reconforge.api.security import create_session
from reconforge.audit import list_audit_events
from reconforge.auth import LocalAuthService
from reconforge.close import write_close_checklist
from reconforge.db import connect, run_migrations
from reconforge.db.exporter import export_database
from reconforge.db.importers import (
    import_account_reconciliations,
    import_close_checklist,
    import_control_tests,
    import_review_state,
)
from reconforge.domain.repositories import WorkspaceRepository
from reconforge.review.state import save_review_state


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _seed_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "reconforge.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        WorkspaceRepository(connection).create(name="Local Migration Workspace")
        auth = LocalAuthService(connection)
        user = auth.init_admin(username="admin", password="Secret-123")
        create_session(connection, user=user)
    finally:
        connection.close()
    return db_path


def _table_count(db_path: Path, table: str) -> int:
    connection = connect(db_path, require_exists=True)
    try:
        row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
        return int(row["count"])
    finally:
        connection.close()


def test_db_export_writes_expected_files_and_excludes_credentials(tmp_path: Path) -> None:
    db_path = _seed_db(tmp_path)
    connection = connect(db_path, require_exists=True)
    try:
        credential_row = connection.execute(
            "SELECT password_hash, password_salt FROM users WHERE username = 'admin'",
        ).fetchone()
        session_row = connection.execute("SELECT token_hash FROM api_sessions").fetchone()
    finally:
        connection.close()

    result = export_database(db_path, tmp_path / "db_export")
    exported_files = {path.name for path in result.paths}
    exported_text = "\n".join(path.read_text(encoding="utf-8") for path in result.paths)
    identity = _read_json(tmp_path / "db_export" / "identity.json")
    metadata = _read_json(tmp_path / "db_export" / "metadata.json")

    assert {
        "metadata.json",
        "domain.json",
        "identity.json",
        "workflow.json",
        "audit_events.json",
        "evidence.json",
        "inventory.json",
        "legacy_imports.json",
    } <= exported_files
    assert metadata["schema_version"] == 12
    assert "users" in identity
    assert "password_hash" not in exported_text
    assert "password_salt" not in exported_text
    assert "token_hash" not in exported_text
    assert "Secret-123" not in exported_text
    assert str(credential_row["password_hash"]) not in exported_text
    assert str(credential_row["password_salt"]) not in exported_text
    assert str(session_row["token_hash"]) not in exported_text

    connection = connect(db_path, require_exists=True)
    try:
        actions = [event.action for event in list_audit_events(connection)]
    finally:
        connection.close()
    assert "db_exported" in actions


def test_import_review_state_is_idempotent_and_audited(tmp_path: Path) -> None:
    db_path = _seed_db(tmp_path)
    state_path = tmp_path / "review_state.json"
    save_review_state(
        state_path,
        {
            "EXC-001": {
                "exception_id": "EXC-001",
                "status": "Under Review",
                "reviewer": "Reviewer",
            },
        },
    )

    first = import_review_state(db_path, state_path)
    second = import_review_state(db_path, state_path)

    connection = connect(db_path, require_exists=True)
    try:
        legacy_rows = connection.execute("SELECT * FROM legacy_import_records").fetchall()
        workflow_rows = connection.execute(
            "SELECT * FROM workflow_objects WHERE object_type = 'legacy_review_exception'",
        ).fetchall()
        actions = [event.action for event in list_audit_events(connection)]
    finally:
        connection.close()

    assert first.imported_count == 1
    assert second.imported_count == 1
    assert len(legacy_rows) == 1
    assert len(workflow_rows) == 1
    assert workflow_rows[0]["object_id"] == "EXC-001"
    assert workflow_rows[0]["status"] == "Under Review"
    assert actions.count("legacy_review_state_imported") == 2


def test_import_close_checklist_creates_close_task_references(tmp_path: Path) -> None:
    db_path = _seed_db(tmp_path)
    close_dir = tmp_path / "close"
    write_close_checklist(close_dir)

    result = import_close_checklist(db_path, close_dir)

    assert result.imported_count == 7
    connection = connect(db_path, require_exists=True)
    try:
        rows = connection.execute("SELECT * FROM workflow_objects WHERE object_type = 'close_task'").fetchall()
        legacy_count = _table_count(db_path, "legacy_import_records")
    finally:
        connection.close()
    assert len(rows) == 7
    assert legacy_count == 7


def test_import_account_reconciliations_and_control_tests(tmp_path: Path) -> None:
    db_path = _seed_db(tmp_path)
    accounts_dir = tmp_path / "accounts"
    controls_dir = tmp_path / "control_testing"
    accounts_dir.mkdir()
    controls_dir.mkdir()
    (accounts_dir / "account_reconciliations.json").write_text(
        json.dumps(
            {
                "account_reconciliations": [
                    {
                        "reconciliation_id": "AR-001",
                        "account_code": "1200",
                        "account_name": "Synthetic inventory",
                        "period": "2026-05",
                        "status": "Reviewed",
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    (controls_dir / "control_tests.json").write_text(
        json.dumps(
            {
                "control_tests": [
                    {
                        "test_id": "CT-001",
                        "control_id": "CTRL-001",
                        "control_name": "Synthetic review control",
                        "status": "Complete",
                    },
                ],
            },
        ),
        encoding="utf-8",
    )

    account_result = import_account_reconciliations(db_path, accounts_dir)
    control_result = import_control_tests(db_path, controls_dir)

    connection = connect(db_path, require_exists=True)
    try:
        account_rows = connection.execute(
            "SELECT * FROM workflow_objects WHERE object_type = 'legacy_account_reconciliation'",
        ).fetchall()
        control_rows = connection.execute(
            "SELECT * FROM workflow_objects WHERE object_type = 'control_test' AND object_id = 'CT-001'",
        ).fetchall()
        legacy_types = {
            str(row["source_type"])
            for row in connection.execute("SELECT source_type FROM legacy_import_records").fetchall()
        }
        actions = [event.action for event in list_audit_events(connection)]
    finally:
        connection.close()

    assert account_result.imported_count == 1
    assert control_result.imported_count == 1
    assert len(account_rows) == 1
    assert account_rows[0]["object_id"] == "AR-001"
    assert len(control_rows) == 1
    assert {"account_reconciliations", "control_tests"} <= legacy_types
    assert "legacy_account_reconciliations_imported" in actions
    assert "legacy_control_tests_imported" in actions
