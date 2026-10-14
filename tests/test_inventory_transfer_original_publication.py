"""Filesystem custody only; these synthetic bytes claim no executed financial cycle."""
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tests import inventory_transfer_original_publication as publisher


def packet(tmp_path: Path) -> tuple[Path, Path, dict[str, Any], dict[str, bytes]]:
    private, output = tmp_path / "private", tmp_path / "public"
    source = private / "capture-original"
    source.mkdir(parents=True)
    output.mkdir()
    raw = b'{"filesystem_custody_fixture":true,"minor":9000000000000000000,"label":"original"}\n'
    result = {"schema_version": "inventory-transfer-oracle-v1", "filesystem_fixture_only": True,
        "original_file_sha256": publisher._hash(raw), "verifier_sha256": "a" * 64}
    stdout = publisher._json_bytes(result, compact=True)
    files = {publisher.RAW: raw,
        "argv-I.json": b'["python","-I","reviewed-helper.py","inventory-transfer-original.json"]\n',
        "argv-I-O.json": b'["python","-I","-O","reviewed-helper.py","inventory-transfer-original.json"]\n',
        "stdout-I.json": stdout, "stdout-I-O.json": stdout, "stderr-I.log": b"", "stderr-I-O.log": b""}
    manifest = {"schema_version": "inventory-transfer-original-oracle-custody-v1", "original_file": publisher.RAW,
        "original_file_sha256": publisher._hash(raw), "original_bytes": len(raw), "verifier_sha256": "a" * 64,
        "source_files_sha256": {"synthetic-reviewed-helper.py": "a" * 64}, "normal_optimized_receipts_equal": True,
        "restore_original_sha256": publisher._hash(raw), "independent_oracle": result,
        "members": [{"name": name, "bytes": len(files[name]), "sha256": publisher._hash(files[name])} for name in publisher.EXECUTION]}
    files[publisher.MANIFEST] = publisher._json_bytes(manifest)
    for name, content in files.items():
        with (source / name).open("xb") as stream:
            stream.write(content)
    verified = {"schema_version": "inventory-transfer-browser-native-verification-v1", "original_oracle_packet": str(source),
        "original_oracle_manifest": manifest, "original_oracle_manifest_sha256": publisher._hash(files[publisher.MANIFEST]),
        "independent_oracle": result, "originals_preserved": True, "restore_rebaseline_allowed": False}
    return private, output, verified, files


def test_exact_eight_original_bytes_publish_without_parsing_or_financial_rewriting(tmp_path: Path) -> None:
    private, output, verified, files = packet(tmp_path)
    trusted = deepcopy(verified)
    result = publisher.publish_inventory_transfer_originals(private, output, verified)
    assert result["verified_against_trusted_memory"] is True and result["financial_bytes_transformed"] is False
    assert result["original_file_sha256"] == verified["original_oracle_manifest"]["original_file_sha256"]
    target = output / publisher.TARGET
    assert {p.name for p in target.iterdir()} == set(files)
    assert all((target / name).read_bytes() == content for name, content in files.items())
    assert all((Path(verified["original_oracle_packet"]) / name).read_bytes() == content for name, content in files.items())
    assert verified == trusted and len(result["members"]) == 8
    with pytest.raises(FileExistsError):
        publisher.publish_inventory_transfer_originals(private, output, verified)
    assert all((target / name).read_bytes() == content for name, content in files.items())


@pytest.mark.parametrize("name", [publisher.RAW, "argv-I.json", "stdout-I.json", publisher.MANIFEST])
def test_changed_original_after_successful_verification_is_not_rebaselined(tmp_path: Path, name: str) -> None:
    private, output, verified, files = packet(tmp_path)
    source = Path(verified["original_oracle_packet"])
    (source / name).write_bytes(files[name] + b"altered-after-verification")
    with pytest.raises(ValueError, match="write-time identity"):
        publisher.publish_inventory_transfer_originals(private, output, verified)
    assert not (output / publisher.TARGET).exists() and (source / name).read_bytes() != files[name]


@pytest.mark.parametrize("place", ["source", "copy"])
@pytest.mark.parametrize("name", [publisher.RAW, "argv-I.json", "stdout-I.json", publisher.MANIFEST])
def test_later_copy_mutates_earlier_original_or_public_copy_and_quarantines_without_deletion(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, place: str, name: str) -> None:
    private, output, verified, files = packet(tmp_path)
    original_copy = publisher._copy_member
    visits = []

    def mutate(source: Path, destination: Path, identity: dict[str, Any]) -> None:
        original_copy(source, destination, identity)
        visits.append(source.name)
        if source.name == publisher.MANIFEST:
            base = source.parent if place == "source" else destination.parent
            (base / name).write_bytes(files[name] + b"late-drift")

    monkeypatch.setattr(publisher, "_copy_member", mutate)
    with pytest.raises(ValueError, match="retained privately"):
        publisher.publish_inventory_transfer_originals(private, output, verified)
    assert tuple(visits) == publisher.NAMES and not (output / publisher.TARGET).exists()
    quarantined = list(private.glob("refused-inventory-transfer-publication-*"))
    assert len(quarantined) == 1 and {path.name for path in quarantined[0].iterdir()} == set(files)
    original_source = Path(verified["original_oracle_packet"])
    assert original_source.exists() and all((original_source / key).exists() for key in files)
    assert (quarantined[0] / name).read_bytes() == (files[name] + b"late-drift" if place == "copy" else files[name])


def test_command_changes_mid_copy_refuse_before_next_original_and_preserve_partial_private(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    private, output, verified, files = packet(tmp_path)
    original_copy = publisher._copy_member
    visits = []

    def mutate(source: Path, destination: Path, identity: dict[str, Any]) -> None:
        original_copy(source, destination, identity)
        visits.append(source.name)
        if source.name == "stdout-I.json":
            (source.parent / "argv-I.json").write_bytes(files["argv-I.json"] + b"changed-original-command")

    monkeypatch.setattr(publisher, "_copy_member", mutate)
    with pytest.raises(ValueError, match="retained privately"):
        publisher.publish_inventory_transfer_originals(private, output, verified)
    assert visits == list(publisher.NAMES[:3]) and not (output / publisher.TARGET).exists()
    partial = next(private.glob("refused-inventory-transfer-publication-*"))
    assert {p.name for p in partial.iterdir()} == set(publisher.NAMES[:3])


@pytest.mark.parametrize("change", ["missing", "extra", "duplicate-memory", "wrong-name", "boolean-size", "oversize", "manifest-anchor", "oracle-anchor", "restore-anchor", "stdout", "stderr", "manifest-fields", "result-size", "source-hash"])
def test_invalid_member_population_bounds_or_trusted_anchors_refuse_before_public_target(tmp_path: Path, change: str) -> None:
    private, output, verified, _ = packet(tmp_path)
    source, manifest = Path(verified["original_oracle_packet"]), verified["original_oracle_manifest"]
    if change == "missing":
        (source / "argv-I.json").unlink()
    elif change == "extra":
        (source / "unexpected-secret.log").write_bytes(b"Synthetic file must never be copied")
    elif change == "duplicate-memory":
        manifest["members"][-1] = deepcopy(manifest["members"][0])
    elif change == "wrong-name":
        manifest["members"][0]["name"] = "../outside.json"
    elif change == "boolean-size":
        manifest["members"][0]["bytes"] = True
    elif change == "oversize":
        manifest["original_bytes"] = publisher.LIMITS[publisher.RAW] + 1
    elif change == "manifest-anchor":
        verified["original_oracle_manifest_sha256"] = "0" * 64
    elif change == "oracle-anchor":
        verified["independent_oracle"] = {**verified["independent_oracle"], "original_file_sha256": "0" * 64}
    elif change == "restore-anchor":
        manifest["restore_original_sha256"] = "0" * 64
    elif change == "manifest-fields":
        manifest["unknown_private_field"] = "Synthetic unknown member is never serialized or published"
    elif change == "result-size":
        verified["independent_oracle"]["unbounded_text"] = "x" * 257
    elif change == "source-hash":
        manifest["source_files_sha256"]["synthetic-reviewed-helper.py"] = "not-an-exact-hash"
    else:
        name = "stdout-I-O.json" if change == "stdout" else "stderr-I.log"
        row = next(row for row in manifest["members"] if row["name"] == name)
        row["sha256"] = "0" * 64
        verified["original_oracle_manifest_sha256"] = publisher._hash(publisher._json_bytes(manifest))
    with pytest.raises(ValueError):
        publisher.publish_inventory_transfer_originals(private, output, verified)
    assert not (output / publisher.TARGET).exists()


def test_output_created_after_admission_remains_exclusive_and_is_never_quarantined_as_owned(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    private, output, verified, _ = packet(tmp_path)
    original_check = publisher._check_bundle

    def appears(directory: Path, expected: dict[str, dict[str, Any]]) -> None:
        original_check(directory, expected)
        (output / publisher.TARGET).mkdir()
        (output / publisher.TARGET / "foreign-owned.txt").write_bytes(b"Must remain untouched")

    monkeypatch.setattr(publisher, "_check_bundle", appears)
    with pytest.raises(FileExistsError):
        publisher.publish_inventory_transfer_originals(private, output, verified)
    assert (output / publisher.TARGET / "foreign-owned.txt").read_bytes() == b"Must remain untouched"
    assert not list(private.glob("refused-inventory-transfer-publication-*"))


@pytest.mark.parametrize("place", ["member", "packet", "public"])
@pytest.mark.parametrize("kind", ["symlink", "reparse"])
def test_symlink_or_reparse_redirect_refuses_without_touching_foreign_owned_bytes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, place: str, kind: str) -> None:
    """Portable lstat simulation covers both redirects without privilege-dependent skip."""
    import stat
    from types import SimpleNamespace

    private, output, verified, files = packet(tmp_path)
    source = Path(verified["original_oracle_packet"])
    selected = source / publisher.RAW if place == "member" else source if place == "packet" else output
    original_stat = Path.lstat

    def reparse(path: Path) -> Any:
        value = original_stat(path)
        if path == selected:
            return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777 if kind == "symlink" else value.st_mode,
                st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024) if kind == "reparse" else 0)
        return value

    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(ValueError, match="redirected"):
        publisher.publish_inventory_transfer_originals(private, output, verified)
    assert not (output / publisher.TARGET).exists() and (source / publisher.RAW).read_bytes() == files[publisher.RAW]


def test_outside_packet_and_overlapping_private_public_boundaries_refuse(tmp_path: Path) -> None:
    private, output, verified, _ = packet(tmp_path)
    outside = tmp_path / "foreign-packet"
    outside.mkdir()
    wrong = {**verified, "original_oracle_packet": str(outside)}
    with pytest.raises(ValueError, match="outside"):
        publisher.publish_inventory_transfer_originals(private, output, wrong)
    inside = private / "public-inside-private"
    inside.mkdir()
    with pytest.raises(ValueError, match="separate"):
        publisher.publish_inventory_transfer_originals(private, inside, verified)
    assert not (output / publisher.TARGET).exists()


def test_real_member_read_is_bounded_even_when_file_grows_after_approved_byte_count(tmp_path: Path) -> None:
    private, output, verified, _ = packet(tmp_path)
    source = Path(verified["original_oracle_packet"])
    path = source / "argv-I.json"
    path.write_bytes(b"x" * (publisher.LIMITS[path.name] + 1))
    with pytest.raises(ValueError, match="finite bound"):
        publisher.publish_inventory_transfer_originals(private, output, verified)
    assert not (output / publisher.TARGET).exists()
