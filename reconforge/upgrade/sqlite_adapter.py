"""Concrete Community SQLite upgrade adapter with isolated compatibility drill."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Literal

from reconforge.db.connection import connect
from reconforge.db.migrations import MIGRATIONS, database_status, run_migrations
from reconforge.upgrade.orchestrator import ApplyReceipt, PreflightEvidence, StepKind, UpgradeError, UpgradeStep


def _schema_semver(version: int) -> str:
    return f"0.0.{version}"


def _version_digest(version: int) -> str:
    return hashlib.sha256(f"reconforge-sqlite-schema:{version}".encode("ascii")).hexdigest()


def _database_digest(path: Path) -> str:
    """Hash canonical SQLite SQL/data output after an integrity check."""

    connection = connect(path, require_exists=True)
    digest = hashlib.sha256()
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or str(integrity[0]) != "ok":
            raise UpgradeError("sqlite_upgrade_integrity_check_failed")
        for line in connection.iterdump():
            digest.update(line.encode("utf-8"))
            digest.update(b"\n")
    finally:
        connection.close()
    return digest.hexdigest()


class SQLiteUpgradeAdapter:
    """Upgrade one closed SQLite database and retain one exact rollback copy."""

    kind: StepKind = "database"

    def __init__(self, *, resource_id: str, database_path: Path, recovery_dir: Path) -> None:
        self.resource_id = resource_id
        self._database_path = database_path.resolve(strict=True)
        if not self._database_path.is_file() or self._database_path.is_symlink():
            raise UpgradeError("sqlite_upgrade_database_path_invalid")
        self._recovery_dir = recovery_dir.resolve()
        self._recovery_dir.mkdir(parents=True, exist_ok=True)
        if self._recovery_dir.is_symlink() or self._recovery_dir == self._database_path.parent:
            raise UpgradeError("sqlite_upgrade_recovery_path_invalid")

    def preflight(self, step: UpgradeStep) -> PreflightEvidence:
        source, target = self._versions(step)
        status = database_status(self._database_path)
        if status.current_version != source or target <= source or target > MIGRATIONS[-1].version:
            raise UpgradeError("sqlite_upgrade_version_unsupported")
        if step.target_sha256 != _version_digest(target):
            raise UpgradeError("sqlite_upgrade_target_digest_mismatch")
        source_digest = _database_digest(self._database_path)
        backup = self._backup_path(step)
        if backup.exists():
            if backup.is_symlink() or _database_digest(backup) != source_digest:
                raise UpgradeError("sqlite_upgrade_rollback_copy_conflict")
        else:
            source_connection = sqlite3.connect(self._database_path)
            target_connection = sqlite3.connect(backup)
            try:
                source_connection.backup(target_connection)
            finally:
                target_connection.close()
                source_connection.close()
            if _database_digest(backup) != source_digest:
                raise UpgradeError("sqlite_upgrade_rollback_copy_mismatch")

        drill = self._recovery_dir / f".{backup.stem}.compatibility-drill.sqlite3"
        if drill.exists():
            drill.unlink()
        try:
            shutil.copy2(backup, drill)
            migrated = run_migrations(drill, target_version=target)
            if migrated.current_version != target or _database_digest(drill) == source_digest:
                raise UpgradeError("sqlite_upgrade_compatibility_drill_failed")
            compatibility_digest = _database_digest(drill)
        finally:
            drill.unlink(missing_ok=True)
        return PreflightEvidence(
            source_digest=source_digest,
            rollback_digest=_database_digest(backup),
            compatibility_digest=compatibility_digest,
        )

    def apply(self, step: UpgradeStep, evidence: PreflightEvidence) -> ApplyReceipt:
        _source, target = self._versions(step)
        if _database_digest(self._database_path) != evidence.source_digest:
            raise UpgradeError("sqlite_upgrade_source_changed_after_preflight")
        result = run_migrations(self._database_path, target_version=target)
        if result.current_version != target:
            raise UpgradeError("sqlite_upgrade_target_not_reached")
        return ApplyReceipt(output_digest=_version_digest(target), rollback_token=self._backup_path(step).name)

    def recover(self, step: UpgradeStep, evidence: PreflightEvidence) -> ApplyReceipt | Literal["not_applied"] | None:
        source, target = self._versions(step)
        backup = self._backup_path(step)
        if not backup.is_file() or backup.is_symlink() or _database_digest(backup) != evidence.rollback_digest:
            return None
        try:
            current = database_status(self._database_path).current_version
        except Exception:
            current = -1
        if current == source and _database_digest(self._database_path) == evidence.source_digest:
            return "not_applied"
        if source < current <= target:
            return ApplyReceipt(output_digest=_version_digest(target), rollback_token=backup.name)
        return None

    def verify(self, step: UpgradeStep, receipt: ApplyReceipt) -> str:
        _source, target = self._versions(step)
        if receipt.rollback_token != self._backup_path(step).name:
            raise UpgradeError("sqlite_upgrade_receipt_invalid")
        if database_status(self._database_path).current_version != target:
            raise UpgradeError("sqlite_upgrade_verification_failed")
        _database_digest(self._database_path)
        return _version_digest(target)

    def rollback(self, step: UpgradeStep, receipt: ApplyReceipt) -> str:
        backup = self._backup_path(step)
        if receipt.rollback_token != backup.name or not backup.is_file() or backup.is_symlink():
            raise UpgradeError("sqlite_upgrade_rollback_copy_invalid")
        temporary = self._database_path.with_name(f".{self._database_path.name}.upgrade-restore.tmp")
        if temporary.exists():
            if temporary.is_symlink():
                raise UpgradeError("sqlite_upgrade_restore_path_invalid")
            temporary.unlink()
        try:
            shutil.copy2(backup, temporary)
            with temporary.open("r+b") as handle:
                os.fsync(handle.fileno())
            for suffix in ("-wal", "-shm"):
                sidecar = Path(f"{self._database_path}{suffix}")
                if sidecar.exists():
                    if sidecar.is_symlink() or not sidecar.is_file():
                        raise UpgradeError("sqlite_upgrade_sidecar_path_invalid")
                    sidecar.unlink()
            os.replace(temporary, self._database_path)
        finally:
            temporary.unlink(missing_ok=True)
        return _database_digest(self._database_path)

    def _versions(self, step: UpgradeStep) -> tuple[int, int]:
        if step.kind != self.kind or step.resource_id != self.resource_id:
            raise UpgradeError("sqlite_upgrade_step_identity_mismatch")
        if step.compatibility_reader != "sqlite-schema-reader-v1":
            raise UpgradeError("sqlite_upgrade_compatibility_reader_unsupported")
        try:
            source = int(step.from_version.removeprefix("0.0."))
            target = int(step.to_version.removeprefix("0.0."))
        except ValueError as exc:
            raise UpgradeError("sqlite_upgrade_schema_version_invalid") from exc
        if step.from_version != _schema_semver(source) or step.to_version != _schema_semver(target):
            raise UpgradeError("sqlite_upgrade_schema_version_invalid")
        return source, target

    def _backup_path(self, step: UpgradeStep) -> Path:
        source, target = self._versions(step)
        return self._recovery_dir / f"{self.resource_id}-v{source}-to-v{target}.rollback.sqlite3"
