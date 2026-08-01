"""Immutable local-object inventory upgrade with atomic catalog cutover."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Literal

from reconforge.upgrade.orchestrator import ApplyReceipt, PreflightEvidence, StepKind, UpgradeError, UpgradeStep

MAX_OBJECTS = 100_000
MAX_MANIFEST_BYTES = 64 * 1024
MAX_CATALOG_BYTES = 64 * 1024 * 1024
_MANIFEST_SUFFIX = ".reconforge-object.json"
_CATALOG_NAME = "reconforge-object-catalog.v1.json"
_VERSION_RE = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _catalog_payload(object_root: Path, *, version: str) -> dict[str, object]:
    if _VERSION_RE.fullmatch(version) is None:
        raise UpgradeError("object_catalog_version_invalid")
    if object_root.is_symlink() or not object_root.is_dir():
        raise UpgradeError("object_catalog_root_invalid")
    manifests: list[Path] = []
    ordinary: set[str] = set()
    for path in object_root.rglob("*"):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise UpgradeError("object_catalog_symlink_rejected")
        if path.is_dir():
            continue
        if not path.is_file():
            raise UpgradeError("object_catalog_special_file_rejected")
        relative = path.relative_to(object_root).as_posix()
        if relative.endswith(_MANIFEST_SUFFIX):
            manifests.append(path)
        else:
            ordinary.add(relative)
    if len(manifests) > MAX_OBJECTS:
        raise UpgradeError("object_catalog_object_limit_exceeded")

    entries: list[dict[str, object]] = []
    paired: set[str] = set()
    for manifest_path in sorted(manifests, key=lambda item: item.relative_to(object_root).as_posix()):
        relative_manifest = manifest_path.relative_to(object_root).as_posix()
        relative_object = relative_manifest[: -len(_MANIFEST_SUFFIX)]
        object_path = object_root.joinpath(*relative_object.split("/"))
        if relative_object not in ordinary or object_path.is_symlink():
            raise UpgradeError("object_catalog_orphan_manifest")
        if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
            raise UpgradeError("object_catalog_manifest_size_exceeded")
        try:
            raw = manifest_path.read_bytes()
            manifest = json.loads(raw)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise UpgradeError("object_catalog_manifest_invalid") from exc
        if not isinstance(manifest, dict) or set(manifest) != {
            "schema_version", "key", "sha256", "size", "content_type", "metadata", "retention_until"
        }:
            raise UpgradeError("object_catalog_manifest_invalid")
        key = manifest.get("key")
        expected_digest = manifest.get("sha256")
        expected_size = manifest.get("size")
        object_metadata = manifest.get("metadata")
        if (
            manifest.get("schema_version") != 1
            or not isinstance(key, str)
            or key != relative_object
            or not isinstance(expected_digest, str)
            or _SHA256_RE.fullmatch(expected_digest) is None
            or not isinstance(expected_size, int)
            or expected_size < 0
            or not isinstance(object_metadata, dict)
            or object_metadata.get("reconforge-sha256") != expected_digest
        ):
            raise UpgradeError("object_catalog_manifest_identity_invalid")
        actual_digest, actual_size = _hash_file(object_path)
        if actual_digest != expected_digest or actual_size != expected_size:
            raise UpgradeError("object_catalog_content_integrity_failed")
        paired.add(relative_object)
        entries.append(
            {
                "key": key,
                "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                "sha256": actual_digest,
                "size": actual_size,
            }
        )
    if ordinary != paired:
        raise UpgradeError("object_catalog_orphan_content")
    return {
        "catalog_version": version,
        "entries": entries,
        "object_count": len(entries),
        "schema": "reconforge-local-object-catalog-v1",
    }


def build_object_catalog(object_root: Path, *, version: str) -> bytes:
    """Build a deterministic catalog only after verifying every immutable object."""

    payload = _catalog_payload(object_root.resolve(strict=True), version=version)
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def write_object_catalog(deployment: Path, object_root: Path, *, version: str) -> str:
    deployment.mkdir(parents=True, exist_ok=False)
    payload = build_object_catalog(object_root, version=version)
    temporary = deployment / f".{_CATALOG_NAME}.tmp"
    temporary.write_bytes(payload)
    os.replace(temporary, deployment / _CATALOG_NAME)
    return hashlib.sha256(payload).hexdigest()


def _catalog_identity(deployment: Path, object_root: Path) -> tuple[str, str]:
    catalog = deployment / _CATALOG_NAME
    if (
        deployment.is_symlink()
        or not deployment.is_dir()
        or catalog.is_symlink()
        or not catalog.is_file()
        or catalog.stat().st_size > MAX_CATALOG_BYTES
    ):
        raise UpgradeError("object_catalog_deployment_invalid")
    if set(path.name for path in deployment.iterdir()) != {_CATALOG_NAME}:
        raise UpgradeError("object_catalog_deployment_expanded")
    try:
        raw = catalog.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise UpgradeError("object_catalog_invalid") from exc
    version = payload.get("catalog_version") if isinstance(payload, dict) else None
    if not isinstance(version, str):
        raise UpgradeError("object_catalog_invalid")
    expected = build_object_catalog(object_root, version=version)
    if raw != expected:
        raise UpgradeError("object_catalog_inventory_changed")
    return version, hashlib.sha256(raw).hexdigest()


class LocalObjectCatalogUpgradeAdapter:
    """Upgrade only the verified catalog; immutable object bytes never move."""

    kind: StepKind = "object_store"

    def __init__(self, *, resource_id: str, object_root: Path, deployment_root: Path) -> None:
        self.resource_id = resource_id
        self._objects = object_root.resolve(strict=True)
        self._root = deployment_root.resolve(strict=True)
        if self._objects == self._root or self._root.is_relative_to(self._objects) or self._objects.is_relative_to(self._root):
            raise UpgradeError("object_catalog_roots_must_be_separate")
        if self._objects.is_symlink() or self._root.is_symlink() or not self._objects.is_dir() or not self._root.is_dir():
            raise UpgradeError("object_catalog_root_invalid")

    def preflight(self, step: UpgradeStep) -> PreflightEvidence:
        self._validate_step(step)
        source_version, source_digest = _catalog_identity(self._current, self._objects)
        if source_version != step.from_version:
            raise UpgradeError("object_catalog_source_version_mismatch")
        target = build_object_catalog(self._objects, version=step.to_version)
        target_digest = hashlib.sha256(target).hexdigest()
        if target_digest != step.target_sha256:
            raise UpgradeError("object_catalog_target_digest_mismatch")
        stage = self._stage(step)
        if stage.exists():
            if _catalog_identity(stage, self._objects) != (step.to_version, target_digest):
                raise UpgradeError("object_catalog_stage_conflict")
        else:
            write_object_catalog(stage, self._objects, version=step.to_version)
        return PreflightEvidence(source_digest, source_digest, target_digest)

    def apply(self, step: UpgradeStep, evidence: PreflightEvidence) -> ApplyReceipt:
        self._validate_step(step)
        if _catalog_identity(self._current, self._objects)[1] != evidence.source_digest:
            raise UpgradeError("object_catalog_state_changed_after_preflight")
        if _catalog_identity(self._stage(step), self._objects)[1] != evidence.compatibility_digest:
            raise UpgradeError("object_catalog_stage_changed_after_preflight")
        rollback = self._rollback_path(step)
        if rollback.exists():
            raise UpgradeError("object_catalog_rollback_path_conflict")
        os.replace(self._current, rollback)
        os.replace(self._stage(step), self._current)
        return ApplyReceipt(evidence.compatibility_digest, rollback.name)

    def recover(self, step: UpgradeStep, evidence: PreflightEvidence) -> ApplyReceipt | Literal["not_applied"] | None:
        self._validate_step(step)
        current = self._identity_or_none(self._current)
        rollback = self._identity_or_none(self._rollback_path(step))
        if current == (step.from_version, evidence.source_digest) and rollback is None:
            return "not_applied"
        if rollback == (step.from_version, evidence.rollback_digest) and (
            current is None or current == (step.to_version, evidence.compatibility_digest)
        ):
            return ApplyReceipt(evidence.compatibility_digest, self._rollback_path(step).name)
        return None

    def verify(self, step: UpgradeStep, receipt: ApplyReceipt) -> str:
        self._validate_step(step)
        if receipt.rollback_token != self._rollback_path(step).name:
            raise UpgradeError("object_catalog_verification_failed")
        if _catalog_identity(self._current, self._objects) != (step.to_version, receipt.output_digest):
            raise UpgradeError("object_catalog_verification_failed")
        return receipt.output_digest

    def rollback(self, step: UpgradeStep, receipt: ApplyReceipt) -> str:
        self._validate_step(step)
        rollback = self._rollback_path(step)
        if receipt.rollback_token != rollback.name or _catalog_identity(rollback, self._objects)[0] != step.from_version:
            raise UpgradeError("object_catalog_rollback_invalid")
        if self._current.exists():
            quarantine = self._root / f"quarantine-object-catalog-{step.to_version}"
            if quarantine.exists():
                raise UpgradeError("object_catalog_quarantine_conflict")
            os.replace(self._current, quarantine)
        os.replace(rollback, self._current)
        return _catalog_identity(self._current, self._objects)[1]

    @property
    def _current(self) -> Path:
        return self._root / "current"

    def _stage(self, step: UpgradeStep) -> Path:
        return self._root / f"stage-{self.resource_id}-{step.to_version}"

    def _rollback_path(self, step: UpgradeStep) -> Path:
        return self._root / f"rollback-{self.resource_id}-{step.from_version}"

    def _validate_step(self, step: UpgradeStep) -> None:
        if step.kind != self.kind or step.resource_id != self.resource_id:
            raise UpgradeError("object_catalog_step_identity_mismatch")
        if step.compatibility_reader != "local-object-catalog-v1":
            raise UpgradeError("object_catalog_compatibility_reader_unsupported")

    def _identity_or_none(self, path: Path) -> tuple[str, str] | None:
        return None if not path.exists() else _catalog_identity(path, self._objects)
