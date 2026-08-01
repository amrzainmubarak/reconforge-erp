from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reconforge.auth import LocalAuthService
from reconforge.cli import app
from reconforge.db import connect, run_migrations
from reconforge.db.encrypted_backup import (
    create_encrypted_backup,
    read_operator_backup_key,
    restore_encrypted_backup,
)
from reconforge.db.exporter import DBBridgeError
from reconforge.domain.repositories import WorkspaceRepository

KEY = bytes(range(32))
runner = CliRunner()


def _database(path: Path, name: str) -> Path:
    run_migrations(path)
    connection = connect(path, require_exists=True)
    try:
        WorkspaceRepository(connection).create(name=name)
        LocalAuthService(connection).init_admin(username="backup-admin", password="Sensitive-Password-123")
    finally:
        connection.close()
    return path


def _workspace_names(path: Path) -> set[str]:
    connection = connect(path, require_exists=True)
    try:
        return {str(row["name"]) for row in connection.execute("SELECT name FROM workspaces")}
    finally:
        connection.close()


def test_encrypted_backup_round_trip_does_not_publish_plaintext(tmp_path: Path) -> None:
    source = _database(tmp_path / "source.db", "Confidential Workspace")
    envelope = tmp_path / "backup.rfbackup"

    created = create_encrypted_backup(source, envelope, key=KEY)
    raw = envelope.read_bytes()

    assert created.path == envelope.resolve()
    assert b"Confidential Workspace" not in raw
    assert b"Sensitive-Password-123" not in raw
    assert not (tmp_path / "backup.json").exists()
    assert not (tmp_path / "manifest.json").exists()

    target = tmp_path / "restored.db"
    restored = restore_encrypted_backup(target, envelope, key=KEY)
    assert restored.db_path == target.resolve()
    assert _workspace_names(target) == {"Confidential Workspace"}


def test_wrong_key_tamper_and_existing_target_fail_without_mutation(tmp_path: Path) -> None:
    source = _database(tmp_path / "source.db", "Source")
    target = _database(tmp_path / "target.db", "Keep Me")
    envelope = tmp_path / "backup.rfbackup"
    create_encrypted_backup(source, envelope, key=KEY)

    with pytest.raises(DBBridgeError, match="integrity"):
        restore_encrypted_backup(target, envelope, key=b"x" * 32, force=True)
    assert _workspace_names(target) == {"Keep Me"}

    document = json.loads(envelope.read_text(encoding="ascii"))
    ciphertext = bytearray(base64.b64decode(document["ciphertext"], validate=True))
    ciphertext[len(ciphertext) // 2] ^= 1
    document["ciphertext"] = base64.b64encode(ciphertext).decode("ascii")
    envelope.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n", encoding="ascii")
    with pytest.raises(DBBridgeError, match="integrity"):
        restore_encrypted_backup(target, envelope, key=KEY, force=True)
    assert _workspace_names(target) == {"Keep Me"}


def test_encrypted_restore_dry_run_and_key_contract(tmp_path: Path) -> None:
    source = _database(tmp_path / "source.db", "Dry Run")
    envelope = tmp_path / "backup.rfbackup"
    with pytest.raises(DBBridgeError, match="32-byte"):
        create_encrypted_backup(source, envelope, key=b"short")
    create_encrypted_backup(source, envelope, key=KEY)
    target = tmp_path / "target.db"
    result = restore_encrypted_backup(target, envelope, key=KEY, dry_run=True)
    assert result.dry_run is True
    assert not target.exists()


def test_operator_key_file_accepts_raw_and_hex_and_rejects_other_lengths(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.key"
    raw_path.write_bytes(KEY)
    hex_path = tmp_path / "hex.key"
    hex_path.write_text(KEY.hex() + "\n", encoding="ascii")
    invalid_path = tmp_path / "invalid.key"
    invalid_path.write_bytes(b"x" * 33)

    assert read_operator_backup_key(raw_path) == KEY
    assert read_operator_backup_key(hex_path) == KEY
    with pytest.raises(DBBridgeError, match="32 raw bytes"):
        read_operator_backup_key(invalid_path)


def test_encrypted_backup_cli_round_trip_and_wrong_key_is_safe(tmp_path: Path) -> None:
    source = _database(tmp_path / "source.db", "CLI Source")
    key_file = tmp_path / "backup.key"
    key_file.write_text(KEY.hex(), encoding="ascii")
    envelope = tmp_path / "backup.rfbackup"
    created = runner.invoke(
        app,
        ["db", "backup-encrypted", "--db", str(source), "--output", str(envelope), "--key-file", str(key_file)],
    )
    assert created.exit_code == 0, created.output
    assert "Encrypted database backup written" in created.output
    assert KEY.hex() not in created.output

    target = _database(tmp_path / "target.db", "Keep CLI")
    wrong_key = tmp_path / "wrong.key"
    wrong_key.write_bytes(b"z" * 32)
    failed = runner.invoke(
        app,
        [
            "db",
            "restore-encrypted",
            "--db",
            str(target),
            "--input",
            str(envelope),
            "--key-file",
            str(wrong_key),
            "--force",
        ],
    )
    assert failed.exit_code == 1
    assert "Traceback" not in failed.output
    assert _workspace_names(target) == {"Keep CLI"}

    restored = runner.invoke(
        app,
        [
            "db",
            "restore-encrypted",
            "--db",
            str(target),
            "--input",
            str(envelope),
            "--key-file",
            str(key_file),
            "--force",
        ],
    )
    assert restored.exit_code == 0, restored.output
    assert _workspace_names(target) == {"CLI Source"}
