from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from reconforge.application.evidence import EvidenceStorageScope
from reconforge.cli import app
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.object_storage import LocalObjectStorageSettings, LocalObjectStore
from reconforge.platform.evidence import OBJECT_STORAGE_BACKEND

runner = CliRunner()


def _evidence_id(db_path: Path) -> str:
    connection = connect(db_path, require_exists=True)
    try:
        row = connection.execute("SELECT id FROM evidence_registry ORDER BY rowid DESC LIMIT 1").fetchone()
    finally:
        connection.close()
    assert row is not None
    return str(row["id"])


def test_cli_registers_and_verifies_offline_retained_evidence(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    source = tmp_path / "bank-statement.txt"
    storage_root = tmp_path / "evidence-objects"
    source.write_text("synthetic statement evidence\n", encoding="utf-8")
    run_migrations(db_path)
    retention_until = (datetime.now(UTC) + timedelta(days=30)).isoformat()

    registered = runner.invoke(
        app,
        [
            "evidence",
            "register",
            "--file",
            str(source),
            "--db",
            str(db_path),
            "--evidence-code",
            "COMMUNITY-RETENTION-1",
            "--storage-backend",
            "local-object-store",
            "--storage-root",
            str(storage_root),
            "--storage-tenant-id",
            "tenant-a",
            "--retention-until",
            retention_until,
        ],
    )
    assert registered.exit_code == 0, registered.output

    evidence_id = _evidence_id(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        row = connection.execute(
            "SELECT storage_backend, storage_tenant_id, workspace_id, storage_key, retention_until "
            "FROM evidence_registry WHERE id = ?",
            (evidence_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    assert row["storage_backend"] == OBJECT_STORAGE_BACKEND
    assert row["storage_tenant_id"] == "tenant-a"
    assert row["retention_until"] is not None

    store = LocalObjectStore(LocalObjectStorageSettings(root=storage_root.resolve()))
    scope = EvidenceStorageScope("tenant-a", str(row["workspace_id"]))
    stored = store.get_bytes(scope, str(row["storage_key"]))
    manifest_path = storage_root / Path(
        *store.key_for(scope, str(row["storage_key"])).split("/")
    )
    manifest = json.loads(
        manifest_path.with_name(manifest_path.name + ".reconforge-object.json").read_text(encoding="utf-8")
    )
    assert stored.content == source.read_bytes()
    assert manifest["retention_until"] == row["retention_until"]

    source.unlink()
    verified = runner.invoke(
        app,
        [
            "evidence",
            "verify",
            "--id",
            evidence_id,
            "--db",
            str(db_path),
            "--storage-backend",
            "local-object-store",
            "--storage-root",
            str(storage_root),
        ],
    )
    assert verified.exit_code == 0, verified.output
    assert "True" in verified.output


def test_cli_local_object_store_rejects_expired_retention_without_registry_row(tmp_path: Path) -> None:
    db_path = tmp_path / "expired.db"
    source = tmp_path / "evidence.txt"
    storage_root = tmp_path / "evidence-objects"
    source.write_text("expired synthetic evidence\n", encoding="utf-8")
    run_migrations(db_path)

    result = runner.invoke(
        app,
        [
            "evidence",
            "register",
            "--file",
            str(source),
            "--db",
            str(db_path),
            "--storage-backend",
            "local-object-store",
            "--storage-root",
            str(storage_root),
            "--storage-tenant-id",
            "tenant-a",
            "--retention-until",
            (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        ],
    )
    assert result.exit_code == 1
    assert "Unable to store evidence artifact in configured object storage" in result.output
    assert _count_evidence(db_path) == 0
    assert [path for path in storage_root.rglob("*") if path.is_file()] == []


def test_cli_default_local_backend_still_rejects_retention_explicitly(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-local.db"
    source = tmp_path / "evidence.txt"
    source.write_text("local synthetic evidence\n", encoding="utf-8")
    run_migrations(db_path)

    result = runner.invoke(
        app,
        [
            "evidence",
            "register",
            "--file",
            str(source),
            "--db",
            str(db_path),
            "--storage-backend",
            "local",
            "--retention-until",
            (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        ],
    )
    assert result.exit_code == 1
    assert "Object-storage options require an explicitly configured object store" in result.output
    assert _count_evidence(db_path) == 0


def _count_evidence(db_path: Path) -> int:
    connection = connect(db_path, require_exists=True)
    try:
        row = connection.execute("SELECT COUNT(*) AS count FROM evidence_registry").fetchone()
    finally:
        connection.close()
    assert row is not None
    return int(row["count"])
