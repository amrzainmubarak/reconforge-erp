"""Authorized application boundary for backup and restore operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from reconforge.auth.policy import CentralPolicyEngine, PolicyEvaluationContext

BACKUP_CREATE_PERMISSION = "operations.backup.create"
RESTORE_EXECUTE_PERMISSION = "operations.restore.execute"


class BackupRestoreAuthorizationError(PermissionError):
    """Raised when an operational backup or restore action is denied."""


@dataclass(frozen=True)
class BackupArtifact:
    path: Path
    sha256: str
    bytes_written: int
    backend: str
    format_version: str


@dataclass(frozen=True)
class RestoreOutcome:
    backend: str
    target: str
    artifact_sha256: str
    rollback_performed: bool


class BackupRestoreAdapter(Protocol):
    def create_backup(self, output_path: Path, *, key: bytes) -> BackupArtifact: ...

    def restore_backup(self, input_path: Path, *, key: bytes) -> RestoreOutcome: ...


class BackupRestoreApplicationService:
    """Authorize high-risk operational actions before touching an adapter."""

    def __init__(self, adapter: BackupRestoreAdapter, *, policy_engine: CentralPolicyEngine | None = None) -> None:
        self._adapter = adapter
        self._policy = policy_engine or CentralPolicyEngine()

    def create_backup(
        self,
        context: PolicyEvaluationContext,
        output_path: Path,
        *,
        key: bytes,
    ) -> BackupArtifact:
        self._require(context, BACKUP_CREATE_PERMISSION)
        return self._adapter.create_backup(output_path, key=key)

    def restore_backup(
        self,
        context: PolicyEvaluationContext,
        input_path: Path,
        *,
        key: bytes,
    ) -> RestoreOutcome:
        self._require(context, RESTORE_EXECUTE_PERMISSION)
        return self._adapter.restore_backup(input_path, key=key)

    def _require(self, context: PolicyEvaluationContext, permission: str) -> None:
        decision = self._policy.evaluate(
            context,
            required_permission=permission,
            enforce_sod=False,
            enforce_ownership=False,
        )
        if not decision.allowed:
            raise BackupRestoreAuthorizationError("Operational backup or restore permission denied.")
