from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import reconforge.reports.client_pack as client_pack_module
from reconforge.cli import app
from reconforge.reports.client_pack import recover_client_pack_publication


class SimulatedCrash(BaseException):
    """Bypass handled-exception rollback to model abrupt process loss."""


def _publication_dirs(tmp_path: Path) -> tuple[Path, Path]:
    output = tmp_path / "output"
    output.mkdir()
    (output / "previous.txt").write_text("previous", encoding="utf-8")
    staging = tmp_path / ".output.staging-test"
    staging.mkdir()
    (staging / "current.txt").write_text("current", encoding="utf-8")
    return output, staging


def _marker(tmp_path: Path) -> Path:
    markers = list(tmp_path.glob(".output.client-pack-transaction-*.json"))
    assert len(markers) == 1
    return markers[0]


def _crash_after_marker_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> tuple[Path, Path, Path]:
    output, staging = _publication_dirs(tmp_path)
    original_write = client_pack_module._write_publication_marker

    def write_then_crash(path: Path, payload: dict[str, object]) -> None:
        original_write(path, payload)
        if payload["phase"] == phase:
            raise SimulatedCrash(phase)

    monkeypatch.setattr(client_pack_module, "_write_publication_marker", write_then_crash)
    with pytest.raises(SimulatedCrash):
        client_pack_module._publish_staged_output(staging, output)
    return output, staging, _marker(tmp_path)


def test_prepared_crash_recovery_aborts_staged_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, staging = _publication_dirs(tmp_path)
    original_replace = Path.replace

    def crash_before_previous_move(path: Path, target: Path) -> Path:
        if path == output:
            raise SimulatedCrash("prepared")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", crash_before_previous_move)
    with pytest.raises(SimulatedCrash):
        client_pack_module._publish_staged_output(staging, output)

    result = recover_client_pack_publication(output)

    assert result.action == "aborted-before-swap"
    assert (output / "previous.txt").read_text(encoding="utf-8") == "previous"
    assert not staging.exists()
    assert not list(tmp_path.glob(".output.*-*"))


def test_previous_moved_crash_recovery_restores_previous_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, staging, _marker_path = _crash_after_marker_phase(
        tmp_path, monkeypatch, "previous-moved"
    )
    assert not output.exists()

    result = recover_client_pack_publication(output)

    assert result.action == "restored-previous"
    assert (output / "previous.txt").read_text(encoding="utf-8") == "previous"
    assert not staging.exists()
    assert not list(tmp_path.glob(".output.*-*"))


def test_published_crash_recovery_finalizes_verified_new_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, staging, _marker_path = _crash_after_marker_phase(
        tmp_path, monkeypatch, "published"
    )
    assert not staging.exists()

    result = recover_client_pack_publication(output)

    assert result.action == "finalized-published"
    assert (output / "current.txt").read_text(encoding="utf-8") == "current"
    assert not (output / "previous.txt").exists()
    assert not list(tmp_path.glob(".output.*-*"))


def test_crash_after_previous_cleanup_confirms_verified_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, staging = _publication_dirs(tmp_path)
    original_remove = client_pack_module._remove_publication_marker

    def crash_before_marker_removal(path: Path) -> None:
        if path.name.startswith(".output.client-pack-transaction-"):
            raise SimulatedCrash("marker-removal")
        original_remove(path)

    monkeypatch.setattr(client_pack_module, "_remove_publication_marker", crash_before_marker_removal)
    with pytest.raises(SimulatedCrash):
        client_pack_module._publish_staged_output(staging, output)
    monkeypatch.setattr(client_pack_module, "_remove_publication_marker", original_remove)

    result = recover_client_pack_publication(output)

    assert result.action == "confirmed-published"
    assert (output / "current.txt").read_text(encoding="utf-8") == "current"
    assert not list(tmp_path.glob(".output.*-*"))


def test_recovery_rejects_tampered_marker_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, staging, marker_path = _crash_after_marker_phase(
        tmp_path, monkeypatch, "previous-moved"
    )
    rollback = next(tmp_path.glob(".output.rollback-*"))
    previous_bytes = (rollback / "previous.txt").read_bytes()
    payload: dict[str, Any] = json.loads(marker_path.read_text(encoding="utf-8"))
    payload["phase"] = "published"
    marker_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="marker is invalid"):
        recover_client_pack_publication(output)

    assert not output.exists()
    assert staging.exists()
    assert (rollback / "previous.txt").read_bytes() == previous_bytes


def test_recovery_rejects_changed_tree_and_unknown_sibling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, staging, _marker_path = _crash_after_marker_phase(
        tmp_path, monkeypatch, "previous-moved"
    )
    (staging / "current.txt").write_text("changed", encoding="utf-8")

    with pytest.raises(ValueError, match="tree digest mismatch"):
        recover_client_pack_publication(output)

    (staging / "current.txt").write_text("current", encoding="utf-8")
    unknown = tmp_path / ".output.rollback-untrusted"
    unknown.mkdir()
    with pytest.raises(ValueError, match="state is ambiguous"):
        recover_client_pack_publication(output)

    assert not output.exists()
    assert staging.exists()
    assert unknown.exists()


def test_recovery_requires_one_marker_and_refuses_symlinked_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(ValueError, match="exactly one valid marker"):
        recover_client_pack_publication(output)

    marker = tmp_path / ".output.client-pack-transaction-fake.json"
    marker.write_text("{}", encoding="utf-8")
    original_is_reparse = client_pack_module._path_is_reparse
    monkeypatch.setattr(
        client_pack_module,
        "_path_is_reparse",
        lambda path: path == marker or original_is_reparse(path),
    )
    with pytest.raises(ValueError, match="exactly one valid marker"):
        recover_client_pack_publication(output)


def test_recovery_refuses_multiple_markers_without_mutation(tmp_path: Path) -> None:
    output, staging = _publication_dirs(tmp_path)
    first = tmp_path / ".output.client-pack-transaction-first.json"
    second = tmp_path / ".output.client-pack-transaction-second.json"
    first.write_text("{}", encoding="utf-8")
    second.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="exactly one valid marker"):
        recover_client_pack_publication(output)

    assert (output / "previous.txt").read_text(encoding="utf-8") == "previous"
    assert (staging / "current.txt").read_text(encoding="utf-8") == "current"
    assert first.exists() and second.exists()


def test_fresh_publication_refuses_unknown_sibling(tmp_path: Path) -> None:
    output = tmp_path / "output"
    staging = tmp_path / ".output.staging-current"
    staging.mkdir()
    (staging / "current.txt").write_text("current", encoding="utf-8")
    unknown = tmp_path / ".output.staging-unknown"
    unknown.mkdir()

    with pytest.raises(ValueError, match="state is ambiguous"):
        client_pack_module._publish_staged_output(staging, output)

    assert not output.exists()
    assert staging.exists() and unknown.exists()


def test_marker_is_path_minimized_and_disclaims_authentication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, _staging, marker_path = _crash_after_marker_phase(
        tmp_path, monkeypatch, "previous-moved"
    )
    payload = json.loads(marker_path.read_text(encoding="utf-8"))

    assert str(tmp_path) not in marker_path.read_text(encoding="utf-8")
    assert payload["output_name"] == output.name
    assert "not authentication" in payload["integrity_boundary"]
    assert len(payload["marker_digest"]) == 64


def test_cli_runs_explicit_recovery_without_printing_local_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, _staging, _marker_path = _crash_after_marker_phase(
        tmp_path, monkeypatch, "previous-moved"
    )

    result = CliRunner().invoke(
        app,
        ["report", "client-pack-recover", "--output", str(output)],
    )

    assert result.exit_code == 0
    assert "restored-previous" in result.stdout
    assert str(tmp_path) not in result.stdout


def test_generate_preserves_transaction_bound_staging_on_unhandled_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    evidence = source / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "record.txt").write_text("current", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    (output / "previous.txt").write_text("previous", encoding="utf-8")
    original_write = client_pack_module._write_publication_marker

    def write_then_crash(path: Path, payload: dict[str, object]) -> None:
        original_write(path, payload)
        if payload["phase"] == "previous-moved":
            raise SimulatedCrash("previous-moved")

    monkeypatch.setattr(client_pack_module, "_write_publication_marker", write_then_crash)
    with pytest.raises(SimulatedCrash):
        client_pack_module.generate_client_pack(source, output)
    monkeypatch.setattr(client_pack_module, "_write_publication_marker", original_write)

    staging = next(tmp_path.glob(".output.staging-*"))
    assert staging.is_dir()
    result = recover_client_pack_publication(output)
    assert result.action == "restored-previous"
    assert (output / "previous.txt").read_text(encoding="utf-8") == "previous"
    assert not staging.exists()


def test_successful_replacement_leaves_no_transaction_artifacts(tmp_path: Path) -> None:
    output, staging = _publication_dirs(tmp_path)

    client_pack_module._publish_staged_output(staging, output)

    assert (output / "current.txt").read_text(encoding="utf-8") == "current"
    assert not list(tmp_path.glob(".output.staging-*"))
    assert not list(tmp_path.glob(".output.rollback-*"))
    assert not list(tmp_path.glob(".output.client-pack-transaction-*"))
