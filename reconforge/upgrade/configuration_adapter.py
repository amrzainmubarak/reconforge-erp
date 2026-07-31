"""Atomic versioned deployment of the existing reconforge.yml contract."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from pathlib import Path
from typing import Literal

from reconforge.config import load_config
from reconforge.upgrade.orchestrator import ApplyReceipt, PreflightEvidence, StepKind, UpgradeError, UpgradeStep
from reconforge.utils.money import STRICT_FINANCIAL_INPUT_POLICY

MAX_CONFIG_BYTES = 1024 * 1024
MAX_MARKER_BYTES = 16 * 1024
_CONFIG_NAME = "reconforge.yml"
_MARKER_NAME = "reconforge-config-deployment.v1.json"
_VERSION_RE = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_configuration_marker(root: Path, *, version: str) -> str:
    if _VERSION_RE.fullmatch(version) is None:
        raise UpgradeError("configuration_upgrade_version_invalid")
    config = root / _CONFIG_NAME
    if not config.is_file() or config.is_symlink() or config.stat().st_size > MAX_CONFIG_BYTES:
        raise UpgradeError("configuration_upgrade_file_invalid")
    load_config(config, financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY)
    digest = _sha256(config)
    payload = {
        "configuration_sha256": digest,
        "schema": "reconforge-config-deployment-v1",
        "version": version,
    }
    temporary = root / f".{_MARKER_NAME}.tmp"
    temporary.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="ascii")
    os.replace(temporary, root / _MARKER_NAME)
    return digest


def _identity(root: Path) -> tuple[str, str]:
    marker_path = root / _MARKER_NAME
    config_path = root / _CONFIG_NAME
    if (
        root.is_symlink()
        or not root.is_dir()
        or marker_path.is_symlink()
        or not marker_path.is_file()
        or marker_path.stat().st_size > MAX_MARKER_BYTES
    ):
        raise UpgradeError("configuration_upgrade_deployment_invalid")
    if config_path.is_symlink() or not config_path.is_file() or config_path.stat().st_size > MAX_CONFIG_BYTES:
        raise UpgradeError("configuration_upgrade_file_invalid")
    for path in root.iterdir():
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not path.is_file() or path.name not in {_CONFIG_NAME, _MARKER_NAME}:
            raise UpgradeError("configuration_upgrade_unexpected_entry")
    try:
        marker = json.loads(marker_path.read_text(encoding="ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpgradeError("configuration_upgrade_marker_invalid") from exc
    if not isinstance(marker, dict) or set(marker) != {"configuration_sha256", "schema", "version"}:
        raise UpgradeError("configuration_upgrade_marker_invalid")
    version = marker.get("version")
    expected = marker.get("configuration_sha256")
    if (
        marker.get("schema") != "reconforge-config-deployment-v1"
        or not isinstance(version, str)
        or _VERSION_RE.fullmatch(version) is None
        or not isinstance(expected, str)
        or re.fullmatch(r"[a-f0-9]{64}", expected) is None
    ):
        raise UpgradeError("configuration_upgrade_marker_invalid")
    load_config(config_path, financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY)
    actual = _sha256(config_path)
    if actual != expected:
        raise UpgradeError("configuration_upgrade_digest_mismatch")
    return version, actual


class ConfigurationUpgradeAdapter:
    kind: StepKind = "configuration"

    def __init__(self, *, resource_id: str, deployment_root: Path, target_config: Path) -> None:
        self.resource_id = resource_id
        self._root = deployment_root.resolve(strict=True)
        self._target = target_config.resolve(strict=True)
        if self._root.is_symlink() or not self._root.is_dir() or self._target.is_symlink() or not self._target.is_file():
            raise UpgradeError("configuration_upgrade_path_invalid")
        if self._target.stat().st_size <= 0 or self._target.stat().st_size > MAX_CONFIG_BYTES:
            raise UpgradeError("configuration_upgrade_file_invalid")

    def preflight(self, step: UpgradeStep) -> PreflightEvidence:
        self._validate_step(step)
        version, source_digest = _identity(self._current)
        if version != step.from_version:
            raise UpgradeError("configuration_upgrade_source_version_mismatch")
        load_config(self._target, financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY)
        target_digest = _sha256(self._target)
        if target_digest != step.target_sha256:
            raise UpgradeError("configuration_upgrade_target_digest_mismatch")
        stage = self._stage(step)
        if stage.exists():
            staged_version, staged_digest = _identity(stage)
            if staged_version != step.to_version or staged_digest != target_digest:
                raise UpgradeError("configuration_upgrade_stage_conflict")
        else:
            stage.mkdir()
            shutil.copy2(self._target, stage / _CONFIG_NAME)
            staged_digest = write_configuration_marker(stage, version=step.to_version)
        return PreflightEvidence(source_digest, source_digest, staged_digest)

    def apply(self, step: UpgradeStep, evidence: PreflightEvidence) -> ApplyReceipt:
        self._validate_step(step)
        if _identity(self._current)[1] != evidence.source_digest or _identity(self._stage(step))[1] != evidence.compatibility_digest:
            raise UpgradeError("configuration_upgrade_state_changed_after_preflight")
        rollback = self._rollback_path(step)
        if rollback.exists():
            raise UpgradeError("configuration_upgrade_rollback_path_conflict")
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
        if receipt.rollback_token != self._rollback_path(step).name or _identity(self._current) != (step.to_version, receipt.output_digest):
            raise UpgradeError("configuration_upgrade_verification_failed")
        return receipt.output_digest

    def rollback(self, step: UpgradeStep, receipt: ApplyReceipt) -> str:
        self._validate_step(step)
        rollback = self._rollback_path(step)
        if receipt.rollback_token != rollback.name or _identity(rollback)[0] != step.from_version:
            raise UpgradeError("configuration_upgrade_rollback_invalid")
        if self._current.exists():
            quarantine = self._root / f"quarantine-config-{step.to_version}"
            if quarantine.exists():
                raise UpgradeError("configuration_upgrade_quarantine_conflict")
            os.replace(self._current, quarantine)
        os.replace(rollback, self._current)
        return _identity(self._current)[1]

    @property
    def _current(self) -> Path:
        return self._root / "current"

    def _stage(self, step: UpgradeStep) -> Path:
        return self._root / f"stage-{self.resource_id}-{step.to_version}"

    def _rollback_path(self, step: UpgradeStep) -> Path:
        return self._root / f"rollback-{self.resource_id}-{step.from_version}"

    def _validate_step(self, step: UpgradeStep) -> None:
        if step.kind != self.kind or step.resource_id != self.resource_id:
            raise UpgradeError("configuration_upgrade_step_identity_mismatch")
        if step.compatibility_reader != "config-v1-reader":
            raise UpgradeError("configuration_upgrade_compatibility_reader_unsupported")

    @staticmethod
    def _identity_or_none(path: Path) -> tuple[str, str] | None:
        return None if not path.exists() else _identity(path)
