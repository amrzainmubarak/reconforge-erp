"""Finite byte-preserving IT1 publication from the caller's trusted memory receipt."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

RAW = "inventory-transfer-original.json"
MANIFEST = "trusted-original-manifest.json"
EXECUTION = ("argv-I.json", "stdout-I.json", "stderr-I.log", "argv-I-O.json", "stdout-I-O.json", "stderr-I-O.log")
NAMES = (RAW, *EXECUTION, MANIFEST)
LIMITS = {RAW: 16_777_216, MANIFEST: 1_048_576,
    **{name: 16_384 if name.startswith("argv-") else 1_048_576 if name.startswith("stdout-") else 65_536 for name in EXECUTION}}
MAX_TOTAL = 20_971_520
TARGET = "inventory-transfer-originals"
HEX = re.compile(r"[0-9a-f]{64}")
MANIFEST_KEYS = frozenset({"schema_version", "original_file", "original_file_sha256", "original_bytes", "verifier_sha256",
    "source_files_sha256", "normal_optimized_receipts_equal", "restore_original_sha256", "independent_oracle", "members"})
CALLBACK_KEYS = ("schema_version", "originals_preserved", "restore_rebaseline_allowed", "original_oracle_packet",
    "original_oracle_manifest", "independent_oracle", "original_oracle_manifest_sha256")


def _require(condition: bool, message: str) -> None:
    if condition is not True:
        raise ValueError(message)


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(value: Any, *, compact: bool = False) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
        **({"separators": (",", ":")} if compact else {"indent": 2})) + "\n").encode("utf-8")


def _no_redirect(path: Path, *, directory: bool) -> None:
    for current in (*reversed(path.parents), path):
        info = current.lstat()
        _require(not stat.S_ISLNK(info.st_mode) and not (getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)), "Original publication refuses redirected filesystem paths")
        _require(stat.S_ISDIR(info.st_mode) if current != path or directory else stat.S_ISREG(info.st_mode),
            "Original publication requires regular owned files and directories")


def _directory(path: Path) -> Path:
    _require(isinstance(path, Path) and path.is_absolute(), "Original publication requires explicit absolute directories")
    selected = Path(os.path.abspath(path))
    _no_redirect(selected, directory=True)
    return selected


def _bytes(path: Path, maximum: int) -> bytes:
    _no_redirect(path, directory=False)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        info = os.fstat(stream.fileno())
        _require(stat.S_ISREG(info.st_mode) and info.st_size <= maximum, "Original publication member exceeds its finite bound")
        raw = stream.read(maximum + 1)
    _require(len(raw) <= maximum, "Original publication member exceeds its finite bound")
    _no_redirect(path, directory=False)
    return raw


def _identity(path: Path, name: str) -> dict[str, Any]:
    raw = _bytes(path, LIMITS[name])
    return {"bytes": len(raw), "sha256": _hash(raw)}


def _expected(verified: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], bytes, dict[str, Any]]:
    _require(isinstance(verified, dict) and verified.get("schema_version") == "inventory-transfer-browser-native-verification-v1"
        and verified.get("originals_preserved") is True and verified.get("restore_rebaseline_allowed") is False,
        "A successful original in-memory callback is required")
    manifest, result = verified.get("original_oracle_manifest"), verified.get("independent_oracle")
    if not isinstance(manifest, dict) or not isinstance(result, dict):
        raise ValueError("Trusted original manifest and oracle result are required")
    _require(set(manifest) == MANIFEST_KEYS and 1 <= len(result) <= 32,
        "Trusted original metadata exceeds its closed manifest or result bound")
    _require(all(isinstance(key, str) and len(key) <= 128 and (
        isinstance(value, str) and len(value) <= 256 or type(value) in (int, bool) and len(str(value)) <= 32 or value is None)
        for key, value in result.items()), "Trusted original result metadata is not bounded scalar evidence")
    sources = manifest.get("source_files_sha256")
    _require(isinstance(sources, dict) and 1 <= len(sources) <= 16 and all(isinstance(key, str) and 0 < len(key) <= 256
        and isinstance(value, str) and HEX.fullmatch(value) is not None for key, value in sources.items()),
        "Trusted original source metadata is not bounded exact hashes")
    _require(manifest.get("schema_version") == "inventory-transfer-original-oracle-custody-v1" and manifest.get("original_file") == RAW
        and manifest.get("normal_optimized_receipts_equal") is True and manifest.get("independent_oracle") == result,
        "Trusted original manifest does not bind its successful result")
    for name in ("original_file_sha256", "restore_original_sha256", "verifier_sha256"):
        _require(isinstance(manifest.get(name), str) and HEX.fullmatch(manifest[name]) is not None,
            "Trusted original manifest requires exact source hashes")
    _require(manifest["restore_original_sha256"] == manifest["original_file_sha256"]
        and result.get("original_file_sha256") == manifest["original_file_sha256"]
        and result.get("verifier_sha256") == manifest["verifier_sha256"], "Trusted original source and oracle anchors differ")
    raw_size = manifest.get("original_bytes")
    _require(type(raw_size) is int and 0 < raw_size <= LIMITS[RAW], "Trusted original byte count is invalid")
    members = manifest.get("members")
    if not isinstance(members, list) or len(members) != len(EXECUTION):
        raise ValueError("The six original execution members are required")
    expected = {RAW: {"bytes": raw_size, "sha256": manifest["original_file_sha256"]}}
    for member in members:
        _require(isinstance(member, dict) and set(member) == {"name", "bytes", "sha256"}, "Trusted execution member fields differ")
        name = member["name"]
        _require(isinstance(name, str) and name in EXECUTION and name not in expected, "Trusted execution membership is not finite and unique")
        _require(type(member["bytes"]) is int and 0 <= member["bytes"] <= LIMITS[name]
            and isinstance(member["sha256"], str) and HEX.fullmatch(member["sha256"]) is not None,
            "Trusted execution member identity is invalid")
        expected[name] = {"bytes": member["bytes"], "sha256": member["sha256"]}
    manifest_raw = _json_bytes(manifest)
    _require(len(manifest_raw) <= LIMITS[MANIFEST] and verified.get("original_oracle_manifest_sha256") == _hash(manifest_raw),
        "Trusted canonical manifest bytes do not match the successful callback")
    expected[MANIFEST] = {"bytes": len(manifest_raw), "sha256": _hash(manifest_raw)}
    _require(set(expected) == set(NAMES) and sum(row["bytes"] for row in expected.values()) <= MAX_TOTAL,
        "The complete original bundle exceeds its finite membership or byte bound")
    stdout = _json_bytes(result, compact=True)
    # Text-mode CLI stdout preserves its platform newline; never normalize retained bytes.
    canonical_outputs = (stdout, stdout[:-1] + b"\r\n")
    _require(expected["stdout-I.json"] == expected["stdout-I-O.json"]
        and expected["stdout-I.json"] in ({"bytes": len(raw), "sha256": _hash(raw)} for raw in canonical_outputs)
        and all(expected[name] == {"bytes": 0, "sha256": _hash(b"")} for name in ("stderr-I.log", "stderr-I-O.log")),
        "Original normal and optimized output identities differ from the successful result")
    return expected, manifest_raw, manifest


def _check_bundle(directory: Path, expected: dict[str, dict[str, Any]]) -> None:
    _no_redirect(directory, directory=True)
    _require({path.name for path in directory.iterdir()} == set(NAMES), "Original publication contains missing or unexpected members")
    for name in NAMES:
        _require(_identity(directory / name, name) == expected[name], "Original publication differs from its trusted write-time identity")


def _copy_member(source: Path, destination: Path, identity: dict[str, Any]) -> None:
    raw = _bytes(source, LIMITS[source.name])
    _require({"bytes": len(raw), "sha256": _hash(raw)} == identity, "Original member changed before its exclusive copy")
    _no_redirect(destination.parent, directory=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(destination, flags, 0o600), "wb") as writer:
        writer.write(raw)
    _require(_identity(source, source.name) == identity and _identity(destination, source.name) == identity,
        "Original member changed during byte-preserving publication")


def publish_inventory_transfer_originals(private_root: Path, output: Path, verified: dict[str, Any]) -> dict[str, Any]:
    """Publish only the original eight files, using no filesystem-derived trust anchors."""
    _require(isinstance(verified, dict), "A successful original in-memory callback is required")
    # The financial proof remains exclusively in its original raw file, not a cloned/serialized projection.
    trusted = deepcopy({key: verified.get(key) for key in CALLBACK_KEYS})
    expected, manifest_raw, manifest = _expected(trusted)
    private, public = _directory(private_root), _directory(output)
    _require(not private.is_relative_to(public) and not public.is_relative_to(private),
        "Public and private original publication boundaries must be separate")
    packet_name = trusted.get("original_oracle_packet")
    if not isinstance(packet_name, str) or len(packet_name) > 4096:
        raise ValueError("The successful original packet path is required")
    source = _directory(Path(packet_name))
    _require(source != private and source.is_relative_to(private), "The original packet is outside its owned private root")
    _check_bundle(source, expected)
    _require(_bytes(source / MANIFEST, LIMITS[MANIFEST]) == manifest_raw, "Original canonical manifest bytes changed")
    target = public / TARGET
    target.mkdir(exist_ok=False)
    try:
        for name in NAMES:
            # Each later copy rechecks all earlier originals against retained memory.
            _check_bundle(source, expected)
            _copy_member(source / name, target / name, expected[name])
        _check_bundle(source, expected)
        _check_bundle(target, expected)
        _require(_bytes(target / MANIFEST, LIMITS[MANIFEST]) == manifest_raw, "Published canonical manifest bytes changed")
    except Exception:
        # Move only this exclusively created target; never remove an existing tree.
        try:
            _directory(private)
            _directory(public)
            _no_redirect(target, directory=True)
            refused = private / ("refused-inventory-transfer-publication-" + uuid4().hex)
            _require(target.parent == public and refused.parent == private and not refused.exists(),
                "Refused original publication quarantine is outside its owned boundary")
            target.rename(refused)
        except Exception:
            raise RuntimeError("Owned original publication quarantine could not be verified") from None
        raise ValueError("Original transfer publication refused; partial copies retained privately") from None
    return {"schema_version": "inventory-transfer-original-publication-v1", "published_directory": TARGET,
        "financial_bytes_transformed": False, "verified_against_trusted_memory": True,
        "original_file_sha256": manifest["original_file_sha256"], "verifier_sha256": manifest["verifier_sha256"],
        "canonical_manifest_sha256": _hash(manifest_raw), "members": [{"name": name, **expected[name]} for name in NAMES]}
