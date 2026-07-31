"""Offline Python-wheel application cutover adapter."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Literal

from reconforge.upgrade.orchestrator import ApplyReceipt, PreflightEvidence, StepKind, UpgradeError, UpgradeStep

MAX_WHEEL_BYTES = 256 * 1024 * 1024
MAX_DEPLOYMENT_FILES = 20_000
MAX_MARKER_BYTES = 16 * 1024
_VERSION_RE = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_MARKER_NAME = "reconforge-deployment.v1.json"


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_content_digest(root: Path) -> str:
    digest = hashlib.sha256()
    count = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root)
        if relative.as_posix() == _MARKER_NAME:
            continue
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise UpgradeError("application_upgrade_symlink_rejected")
        if path.is_dir():
            continue
        if not path.is_file():
            raise UpgradeError("application_upgrade_special_file_rejected")
        count += 1
        if count > MAX_DEPLOYMENT_FILES:
            raise UpgradeError("application_upgrade_file_count_exceeded")
        encoded = relative.as_posix().encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        digest.update(bytes.fromhex(_file_digest(path)))
    if count == 0:
        raise UpgradeError("application_upgrade_empty_deployment")
    return digest.hexdigest()


def write_deployment_marker(root: Path, *, version: str, artifact_sha256: str) -> str:
    """Seal an already staged deployment with a closed content manifest."""

    if _VERSION_RE.fullmatch(version) is None or _SHA256_RE.fullmatch(artifact_sha256) is None:
        raise UpgradeError("application_upgrade_marker_identity_invalid")
    content_digest = _tree_content_digest(root)
    marker = {
        "artifact_sha256": artifact_sha256,
        "content_sha256": content_digest,
        "schema": "reconforge-deployment-v1",
        "version": version,
    }
    temporary = root / f".{_MARKER_NAME}.tmp"
    temporary.write_text(json.dumps(marker, sort_keys=True, separators=(",", ":")) + "\n", encoding="ascii")
    os.replace(temporary, root / _MARKER_NAME)
    return content_digest


def _deployment_identity(root: Path) -> tuple[str, str, str]:
    marker_path = root / _MARKER_NAME
    if (
        not root.is_dir()
        or root.is_symlink()
        or not marker_path.is_file()
        or marker_path.is_symlink()
        or marker_path.stat().st_size > MAX_MARKER_BYTES
    ):
        raise UpgradeError("application_upgrade_deployment_invalid")
    try:
        marker = json.loads(marker_path.read_text(encoding="ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpgradeError("application_upgrade_marker_invalid") from exc
    if not isinstance(marker, dict) or set(marker) != {"artifact_sha256", "content_sha256", "schema", "version"}:
        raise UpgradeError("application_upgrade_marker_invalid")
    version = marker.get("version")
    artifact = marker.get("artifact_sha256")
    expected = marker.get("content_sha256")
    if marker.get("schema") != "reconforge-deployment-v1" or not isinstance(version, str) or not isinstance(artifact, str) or not isinstance(expected, str):
        raise UpgradeError("application_upgrade_marker_invalid")
    if _VERSION_RE.fullmatch(version) is None or _SHA256_RE.fullmatch(artifact) is None or _SHA256_RE.fullmatch(expected) is None:
        raise UpgradeError("application_upgrade_marker_invalid")
    actual = _tree_content_digest(root)
    if actual != expected:
        raise UpgradeError("application_upgrade_content_digest_mismatch")
    return version, artifact, actual


class PythonWheelApplicationAdapter:
    """Install one local wheel offline, smoke it, and atomically switch directories."""

    kind: StepKind = "application"

    def __init__(self, *, resource_id: str, deployment_root: Path, wheel_path: Path) -> None:
        self.resource_id = resource_id
        self._root = deployment_root.resolve(strict=True)
        self._wheel = wheel_path.resolve(strict=True)
        if not self._root.is_dir() or self._root.is_symlink() or not self._wheel.is_file() or self._wheel.is_symlink():
            raise UpgradeError("application_upgrade_path_invalid")
        if self._wheel.stat().st_size <= 0 or self._wheel.stat().st_size > MAX_WHEEL_BYTES:
            raise UpgradeError("application_upgrade_wheel_size_invalid")

    def preflight(self, step: UpgradeStep) -> PreflightEvidence:
        self._validate_step(step)
        current = self._current
        version, _artifact, source_digest = _deployment_identity(current)
        if version != step.from_version:
            raise UpgradeError("application_upgrade_source_version_mismatch")
        wheel_digest = _file_digest(self._wheel)
        if wheel_digest != step.target_sha256:
            raise UpgradeError("application_upgrade_wheel_digest_mismatch")
        stage = self._stage(step)
        if stage.exists():
            self._require_safe_directory(stage)
            staged_version, staged_artifact, compatibility_digest = _deployment_identity(stage)
            if staged_version != step.to_version or staged_artifact != wheel_digest:
                raise UpgradeError("application_upgrade_stage_conflict")
        else:
            command = [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-input",
                "--no-index",
                "--no-deps",
                "--target",
                str(stage),
                str(self._wheel),
            ]
            result = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)  # nosec B603
            if result.returncode != 0:
                if stage.exists():
                    self._quarantine(stage, f"failed-stage-{step.to_version}")
                raise UpgradeError("application_upgrade_offline_install_failed")
            compatibility_digest = write_deployment_marker(stage, version=step.to_version, artifact_sha256=wheel_digest)
        self._smoke(stage, step.to_version)
        return PreflightEvidence(
            source_digest=source_digest,
            rollback_digest=source_digest,
            compatibility_digest=compatibility_digest,
        )

    def apply(self, step: UpgradeStep, evidence: PreflightEvidence) -> ApplyReceipt:
        self._validate_step(step)
        if _deployment_identity(self._current)[2] != evidence.source_digest:
            raise UpgradeError("application_upgrade_source_changed_after_preflight")
        stage = self._stage(step)
        if _deployment_identity(stage)[2] != evidence.compatibility_digest:
            raise UpgradeError("application_upgrade_stage_changed_after_preflight")
        rollback = self._rollback_path(step)
        if rollback.exists():
            raise UpgradeError("application_upgrade_rollback_path_conflict")
        os.replace(self._current, rollback)
        os.replace(stage, self._current)
        return ApplyReceipt(output_digest=evidence.compatibility_digest, rollback_token=rollback.name)

    def recover(self, step: UpgradeStep, evidence: PreflightEvidence) -> ApplyReceipt | Literal["not_applied"] | None:
        self._validate_step(step)
        current = self._identity_or_none(self._current)
        rollback = self._identity_or_none(self._rollback_path(step))
        stage = self._identity_or_none(self._stage(step))
        if current is not None and current[0] == step.from_version and current[2] == evidence.source_digest and rollback is None:
            return "not_applied"
        if (
            rollback is not None
            and rollback[0] == step.from_version
            and rollback[2] == evidence.rollback_digest
            and (current is None or (current[0] == step.to_version and current[2] == evidence.compatibility_digest))
        ):
            return ApplyReceipt(output_digest=evidence.compatibility_digest, rollback_token=self._rollback_path(step).name)
        if current is None and rollback is None and stage is not None:
            return "not_applied"
        return None

    def verify(self, step: UpgradeStep, receipt: ApplyReceipt) -> str:
        self._validate_step(step)
        if receipt.rollback_token != self._rollback_path(step).name:
            raise UpgradeError("application_upgrade_receipt_invalid")
        version, artifact, digest = _deployment_identity(self._current)
        if version != step.to_version or artifact != step.target_sha256 or digest != receipt.output_digest:
            raise UpgradeError("application_upgrade_verification_failed")
        self._smoke(self._current, step.to_version)
        return digest

    def rollback(self, step: UpgradeStep, receipt: ApplyReceipt) -> str:
        self._validate_step(step)
        rollback = self._rollback_path(step)
        if receipt.rollback_token != rollback.name:
            raise UpgradeError("application_upgrade_receipt_invalid")
        version, _artifact, source_digest = _deployment_identity(rollback)
        if version != step.from_version:
            raise UpgradeError("application_upgrade_rollback_identity_invalid")
        if self._current.exists():
            current = _deployment_identity(self._current)
            if current[0] == step.from_version and current[2] == source_digest:
                return source_digest
            self._quarantine(self._current, f"rolled-back-target-{step.to_version}")
        os.replace(rollback, self._current)
        restored = _deployment_identity(self._current)[2]
        self._smoke(self._current, step.from_version)
        return restored

    @property
    def _current(self) -> Path:
        return self._root / "current"

    def _stage(self, step: UpgradeStep) -> Path:
        return self._root / f"stage-{self.resource_id}-{step.to_version}"

    def _rollback_path(self, step: UpgradeStep) -> Path:
        return self._root / f"rollback-{self.resource_id}-{step.from_version}"

    def _validate_step(self, step: UpgradeStep) -> None:
        if step.kind != self.kind or step.resource_id != self.resource_id:
            raise UpgradeError("application_upgrade_step_identity_mismatch")
        if step.compatibility_reader != "wheel-import-v1":
            raise UpgradeError("application_upgrade_compatibility_reader_unsupported")
        expected_name = f"reconforge_erp-{step.to_version}-py3-none-any.whl"
        if self._wheel.name != expected_name:
            raise UpgradeError("application_upgrade_wheel_name_mismatch")

    @staticmethod
    def _smoke(root: Path, version: str) -> None:
        script = (
            "import pathlib,sys;"
            f"sys.path.insert(0,{str(root)!r});"
            "import reconforge;"
            f"assert reconforge.__version__=={version!r};"
            "assert pathlib.Path(reconforge.__file__).resolve().is_relative_to(pathlib.Path(sys.path[0]).resolve())"
        )
        result = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True, timeout=30, check=False)  # nosec B603
        if result.returncode != 0:
            raise UpgradeError("application_upgrade_smoke_failed")

    def _identity_or_none(self, path: Path) -> tuple[str, str, str] | None:
        if not path.exists():
            return None
        return _deployment_identity(path)

    @staticmethod
    def _require_safe_directory(path: Path) -> None:
        if not path.is_dir() or path.is_symlink():
            raise UpgradeError("application_upgrade_directory_invalid")

    def _quarantine(self, path: Path, label: str) -> Path:
        self._require_safe_directory(path)
        for counter in range(1, 1000):
            target = self._root / f"quarantine-{label}-{counter:03d}"
            if not target.exists():
                os.replace(path, target)
                return target
        raise UpgradeError("application_upgrade_quarantine_exhausted")
