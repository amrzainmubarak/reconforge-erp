from __future__ import annotations

import ast
import json
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import reconforge.reports.client_pack as client_pack_module
from reconforge.io.ingress import FileIngressError
from reconforge.reports.client_pack import (
    ClientPackOptions,
    generate_client_pack,
    verify_client_pack_manifest_payload,
)
from reconforge.utils.money import STRICT_FINANCIAL_INPUT_POLICY


def _write_evidence(root: Path, name: str, payload: bytes) -> Path:
    evidence = root / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    path = evidence / name
    path.write_bytes(payload)
    return path


def _existing_output(root: Path) -> tuple[Path, Path]:
    output = root / "output"
    output.mkdir()
    sentinel = output / "existing-private-output.txt"
    sentinel.write_text("must-remain", encoding="utf-8")
    return output, sentinel


def _temporary_pack_paths(parent: Path, output_name: str = "output") -> list[Path]:
    return sorted(
        [
            *parent.glob(f".{output_name}.staging-*"),
            *parent.glob(f".{output_name}.rollback-*"),
        ]
    )


def test_non_redacted_oversize_rejects_before_hashing_or_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source = _write_evidence(source_root, "large.bin", b"x")
    with source.open("r+b") as handle:
        handle.seek(client_pack_module.CLIENT_PACK_MAX_FILE_BYTES)
        handle.write(b"x")
    output, sentinel = _existing_output(tmp_path)
    monkeypatch.setattr(
        client_pack_module,
        "_sha256",
        lambda _path: pytest.fail("oversized copy reached fingerprint hashing"),
    )

    with pytest.raises(ValueError, match=r"^Client pack source input is invalid$") as captured:
        generate_client_pack(source_root, output)

    assert isinstance(captured.value.__cause__, FileIngressError)
    assert captured.value.__cause__.code == "file_size_limit"
    assert sentinel.read_text(encoding="utf-8") == "must-remain"
    assert _temporary_pack_paths(tmp_path) == []


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [(b"private=\xff", "text_encoding_invalid"), (b"123456789", "text_line_limit")],
    ids=["encoding", "line-limit"],
)
def test_text_redaction_rejects_invalid_input_before_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    expected_code: str,
) -> None:
    source_root = tmp_path / "source"
    _write_evidence(source_root, "private.txt", payload)
    output, sentinel = _existing_output(tmp_path)
    if expected_code == "text_line_limit":
        monkeypatch.setattr(client_pack_module, "CLIENT_PACK_MAX_TEXT_LINE_CHARACTERS", 8)

    with pytest.raises(
        ValueError,
        match=r"^Client pack text redaction input is invalid$",
    ) as captured:
        generate_client_pack(
            source_root,
            output,
            redact_names=True,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )

    assert isinstance(captured.value.__cause__, FileIngressError)
    assert captured.value.__cause__.code == expected_code
    assert sentinel.read_text(encoding="utf-8") == "must-remain"
    assert _temporary_pack_paths(tmp_path) == []


def test_text_redaction_processes_one_bounded_line_at_a_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("first\nsecond\n", encoding="utf-8", newline="")
    target = tmp_path / "output" / "target.txt"
    target.parent.mkdir()
    seen: list[str] = []

    def record_line(line: str, _options: ClientPackOptions) -> str:
        seen.append(line)
        return line.upper()

    monkeypatch.setattr(client_pack_module, "_redact_text", record_line)

    client_pack_module._redact_text_file(source, target, ClientPackOptions(redact_names=True))

    assert seen == ["first\n", "second\n"]
    assert target.read_text(encoding="utf-8") == "FIRST\nSECOND\n"
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_source_count_and_aggregate_size_limits_precede_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    _write_evidence(source_root, "first.bin", b"12")
    _write_evidence(source_root, "second.bin", b"34")
    output, sentinel = _existing_output(tmp_path)

    monkeypatch.setattr(client_pack_module, "CLIENT_PACK_MAX_SOURCE_FILES", 1)
    with pytest.raises(ValueError) as count_error:
        generate_client_pack(source_root, output)
    assert isinstance(count_error.value.__cause__, FileIngressError)
    assert count_error.value.__cause__.code == "file_count_limit"
    assert sentinel.read_text(encoding="utf-8") == "must-remain"

    monkeypatch.setattr(client_pack_module, "CLIENT_PACK_MAX_SOURCE_FILES", 10)
    monkeypatch.setattr(client_pack_module, "CLIENT_PACK_MAX_TOTAL_SOURCE_BYTES", 3)
    with pytest.raises(ValueError) as size_error:
        generate_client_pack(source_root, output)
    assert isinstance(size_error.value.__cause__, FileIngressError)
    assert size_error.value.__cause__.code == "file_total_size_limit"
    assert sentinel.read_text(encoding="utf-8") == "must-remain"
    assert _temporary_pack_paths(tmp_path) == []


def test_directory_enumeration_limit_precedes_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    _write_evidence(source_root, "first.bin", b"1")
    _write_evidence(source_root, "second.bin", b"2")
    output, sentinel = _existing_output(tmp_path)
    monkeypatch.setattr(client_pack_module, "CLIENT_PACK_MAX_DIRECTORY_ENTRIES", 1)

    with pytest.raises(ValueError) as captured:
        generate_client_pack(source_root, output)

    assert isinstance(captured.value.__cause__, FileIngressError)
    assert captured.value.__cause__.code == "directory_entry_limit"
    assert sentinel.read_text(encoding="utf-8") == "must-remain"
    assert _temporary_pack_paths(tmp_path) == []


def test_symlink_metadata_is_rejected_before_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source = _write_evidence(source_root, "private.bin", b"private")
    output, sentinel = _existing_output(tmp_path)
    original_lstat = Path.lstat

    def marked_symlink(path: Path) -> Any:
        if path == source:
            return SimpleNamespace(st_mode=stat.S_IFLNK, st_size=7)
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", marked_symlink)

    with pytest.raises(ValueError) as captured:
        generate_client_pack(source_root, output)

    assert isinstance(captured.value.__cause__, FileIngressError)
    assert captured.value.__cause__.code == "file_not_regular"
    assert sentinel.read_text(encoding="utf-8") == "must-remain"
    assert _temporary_pack_paths(tmp_path) == []


def test_generation_failure_keeps_complete_existing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    _write_evidence(source_root, "private.bin", b"new-private-content")
    output, sentinel = _existing_output(tmp_path)

    def fail_manifest(*_args: object, **_kwargs: object) -> Path:
        raise OSError("simulated manifest failure")

    monkeypatch.setattr(client_pack_module, "_write_manifest", fail_manifest)

    with pytest.raises(OSError, match="simulated manifest failure"):
        generate_client_pack(source_root, output)

    assert sentinel.read_text(encoding="utf-8") == "must-remain"
    assert list(output.iterdir()) == [sentinel]
    assert _temporary_pack_paths(tmp_path) == []


def test_concurrent_source_change_keeps_complete_existing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source = _write_evidence(source_root, "private.bin", b"original")
    output, sentinel = _existing_output(tmp_path)
    original_write_pack_text = client_pack_module._write_pack_text

    def mutate_after_copy(*args: Any, **kwargs: Any) -> tuple[Path, Path, Path]:
        result = original_write_pack_text(*args, **kwargs)
        source.write_bytes(b"changed!")
        return result

    monkeypatch.setattr(client_pack_module, "_write_pack_text", mutate_after_copy)

    with pytest.raises(ValueError, match="changed during generation"):
        generate_client_pack(source_root, output)

    assert sentinel.read_text(encoding="utf-8") == "must-remain"
    assert list(output.iterdir()) == [sentinel]
    assert _temporary_pack_paths(tmp_path) == []


def test_files_created_after_selection_are_not_copied_or_manifested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    _write_evidence(source_root, "selected.bin", b"selected")
    output = tmp_path / "output"
    original_create_staging = client_pack_module._create_staging_dir

    def create_late_files(output_dir: Path) -> Path:
        _write_evidence(source_root, "late.bin", b"late-private")
        (source_root / "summary.md").write_text("late summary", encoding="utf-8")
        return original_create_staging(output_dir)

    monkeypatch.setattr(client_pack_module, "_create_staging_dir", create_late_files)

    artifacts = generate_client_pack(source_root, output)

    assert (output / "evidence" / "selected.bin").read_bytes() == b"selected"
    assert not (output / "evidence" / "late.bin").exists()
    assert not (output / "source_summary.md").exists()
    assert all("late" not in path.name for path in artifacts.included_files)


def test_successful_publication_replaces_stale_output_and_rebases_paths(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _write_evidence(source_root, "private.bin", b"current")
    output, sentinel = _existing_output(tmp_path)
    hidden_stale = output / ".stale-private"
    hidden_stale.write_text("stale", encoding="utf-8")

    artifacts = generate_client_pack(source_root, output)

    assert not sentinel.exists()
    assert not hidden_stale.exists()
    assert artifacts.output_dir == output
    assert artifacts.manifest_path == output / "files_manifest.json"
    assert all(path.exists() and path.is_relative_to(output) for path in artifacts.included_files)
    assert _temporary_pack_paths(tmp_path) == []


def test_publish_failure_restores_previous_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, sentinel = _existing_output(tmp_path)
    staging = tmp_path / ".output.staging-test"
    staging.mkdir()
    (staging / "new.txt").write_text("new", encoding="utf-8")
    original_replace = Path.replace

    def fail_staging_publish(path: Path, target: Path) -> Path:
        if path == staging:
            raise OSError("simulated publish failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_staging_publish)

    with pytest.raises(OSError, match="simulated publish failure"):
        client_pack_module._publish_staged_output(staging, output)

    assert sentinel.read_text(encoding="utf-8") == "must-remain"
    assert not list(tmp_path.glob(".output.rollback-*"))
    assert staging.exists()


def test_rollback_cleanup_failure_restores_previous_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, sentinel = _existing_output(tmp_path)
    staging = tmp_path / ".output.staging-test"
    staging.mkdir()
    (staging / "new.txt").write_text("new", encoding="utf-8")
    original_rmtree = client_pack_module.rmtree

    def fail_rollback_cleanup(path: Path) -> None:
        if path.name.startswith(".output.rollback-"):
            raise OSError("simulated rollback cleanup failure")
        original_rmtree(path)

    monkeypatch.setattr(client_pack_module, "rmtree", fail_rollback_cleanup)

    with pytest.raises(OSError, match="simulated rollback cleanup failure"):
        client_pack_module._publish_staged_output(staging, output)

    assert sentinel.read_text(encoding="utf-8") == "must-remain"
    assert (staging / "new.txt").read_text(encoding="utf-8") == "new"
    assert not list(tmp_path.glob(".output.rollback-*"))


def test_output_cannot_contain_source_or_enter_evidence_tree(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_evidence(source_root, "private.bin", b"private")
    nested_output = source_root / "evidence" / "client-pack"

    with pytest.raises(ValueError, match="separate from the source"):
        generate_client_pack(source_root, nested_output)

    assert not nested_output.exists()

    with pytest.raises(ValueError, match="separate from the source"):
        generate_client_pack(source_root, tmp_path)


def test_compatible_nested_output_outside_evidence_is_staged_safely(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _write_evidence(source_root, "private.bin", b"private")
    output = source_root / "client_pack"

    artifacts = generate_client_pack(source_root, output)

    assert artifacts.output_dir == output
    assert artifacts.manifest_path.exists()
    assert _temporary_pack_paths(source_root, "client_pack") == []


def test_copy_policy_constants_and_ast_exclude_unbounded_helpers() -> None:
    assert client_pack_module.CLIENT_PACK_MAX_SOURCE_FILES == 10_000
    assert client_pack_module.CLIENT_PACK_MAX_DIRECTORY_ENTRIES == 20_000
    assert client_pack_module.CLIENT_PACK_MAX_FILE_BYTES == 64 * 1024 * 1024
    assert client_pack_module.CLIENT_PACK_MAX_TOTAL_SOURCE_BYTES == 512 * 1024 * 1024
    assert client_pack_module.CLIENT_PACK_MAX_TEXT_LINE_CHARACTERS == 1024 * 1024

    tree = ast.parse(Path(client_pack_module.__file__).read_text(encoding="utf-8"))
    forbidden: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in {
            "copy",
            "copy2",
            "copyfile",
            "copyfileobj",
        }:
            forbidden.append(f"{node.func.id}:{node.lineno}")
        if isinstance(node.func, ast.Attribute) and node.func.attr in {
            "read_bytes",
            "read_text",
        }:
            forbidden.append(f"{node.func.attr}:{node.lineno}")

    assert forbidden == []


def test_output_manifest_recheck_uses_bounded_enumeration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    _write_evidence(source_root, "private.bin", b"private")
    artifacts = generate_client_pack(
        source_root,
        tmp_path / "output",
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    payload = json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))
    monkeypatch.setattr(client_pack_module, "CLIENT_PACK_MAX_DIRECTORY_ENTRIES", 1)

    with pytest.raises(ValueError, match="output fingerprint verification failed") as captured:
        verify_client_pack_manifest_payload(payload, output_dir=artifacts.output_dir)

    assert isinstance(captured.value.__cause__, ValueError)
    assert isinstance(captured.value.__cause__.__cause__, FileIngressError)
    assert captured.value.__cause__.__cause__.code == "directory_entry_limit"
