from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

import reconforge.db.exporter as exporter
from reconforge.cli import app
from reconforge.db import run_migrations
from reconforge.db.exporter import DBBridgeError, export_database, recover_database_export_publication


class SimulatedCrash(BaseException):
    pass


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "reconforge.db"
    run_migrations(path)
    return path


def _crash_at_phase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str) -> Path:
    database = _database(tmp_path)
    output = tmp_path / "export"
    output.mkdir()
    (output / "operator-note.txt").write_text("previous", encoding="utf-8")
    original = exporter._write_marker

    def write_then_crash(path: Path, payload: dict[str, object]) -> None:
        original(path, payload)
        if payload["phase"] == phase:
            raise SimulatedCrash(phase)

    monkeypatch.setattr(exporter, "_write_marker", write_then_crash)
    with pytest.raises(SimulatedCrash):
        export_database(database, output)
    monkeypatch.setattr(exporter, "_write_marker", original)
    return output


def test_export_manifest_binds_exact_complete_artifact_set(tmp_path: Path) -> None:
    result = export_database(_database(tmp_path), tmp_path / "export")
    manifest = json.loads((result.output_dir / "export_manifest.json").read_text("utf-8"))
    schema = json.loads(Path("docs/schemas/database_export_manifest.schema.json").read_text("utf-8"))

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(manifest)
    assert set(manifest["artifacts"]) == {path.name for path in result.paths} - {"export_manifest.json"}
    exporter._expected_artifacts(result.output_dir)
    (result.output_dir / "metadata.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(DBBridgeError, match="integrity check failed"):
        exporter._expected_artifacts(result.output_dir)


def test_successful_replacement_removes_stale_files_and_transaction_artifacts(tmp_path: Path) -> None:
    database = _database(tmp_path)
    output = tmp_path / "export"
    output.mkdir()
    (output / "stale.txt").write_text("old", encoding="utf-8")

    result = export_database(database, output)

    assert not (output / "stale.txt").exists()
    assert (output / "export_manifest.json") in result.paths
    assert not list(tmp_path.glob(".export.*-*"))


def test_handled_swap_failure_restores_previous_export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = _database(tmp_path)
    output = tmp_path / "export"
    output.mkdir()
    previous = output / "previous.txt"
    previous.write_text("previous", encoding="utf-8")
    original_replace = Path.replace

    def fail_staging_publish(path: Path, target: Path) -> Path:
        if path.name.startswith(".export.staging-") and target == output:
            raise OSError("simulated publication failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_staging_publish)
    with pytest.raises(DBBridgeError, match="Unable to export"):
        export_database(database, output)

    assert previous.read_text("utf-8") == "previous"
    assert not list(tmp_path.glob(".export.*-*"))


def test_publication_refuses_unknown_sibling_without_replacing_output(tmp_path: Path) -> None:
    database = _database(tmp_path)
    output = tmp_path / "export"
    output.mkdir()
    previous = output / "previous.txt"
    previous.write_text("previous", encoding="utf-8")
    unknown = tmp_path / ".export.rollback-untrusted"
    unknown.mkdir()

    with pytest.raises(DBBridgeError, match="Unable to export"):
        export_database(database, output)

    assert previous.read_text("utf-8") == "previous"
    assert unknown.exists()


def test_previous_moved_crash_recovery_restores_previous_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = _crash_at_phase(tmp_path, monkeypatch, "previous-moved")
    assert not output.exists()

    recovered = recover_database_export_publication(output)

    assert recovered.action == "restored-previous"
    assert (output / "operator-note.txt").read_text("utf-8") == "previous"
    assert not list(tmp_path.glob(".export.*-*"))


def test_published_crash_recovery_finalizes_verified_export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = _crash_at_phase(tmp_path, monkeypatch, "published")

    recovered = recover_database_export_publication(output)

    assert recovered.action == "finalized-published"
    exporter._expected_artifacts(output)
    assert not (output / "operator-note.txt").exists()


def test_recovery_rejects_tampered_marker_without_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = _crash_at_phase(tmp_path, monkeypatch, "previous-moved")
    marker = next(tmp_path.glob(".export.db-export-transaction-*.json"))
    payload = json.loads(marker.read_text("utf-8"))
    payload["phase"] = "published"
    marker.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DBBridgeError, match="marker is invalid"):
        recover_database_export_publication(output)

    assert next(tmp_path.glob(".export.rollback-*"), None) is not None


def test_cli_recovery_does_not_disclose_local_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = _crash_at_phase(tmp_path, monkeypatch, "previous-moved")

    result = CliRunner().invoke(app, ["db", "export-recover", "--output", str(output)])

    assert result.exit_code == 0
    assert "restored-previous" in result.stdout
    assert str(tmp_path) not in result.stdout
