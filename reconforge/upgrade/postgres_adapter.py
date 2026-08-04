"""PostgreSQL Alembic upgrade adapter with encrypted compatibility restore."""

from __future__ import annotations

import hashlib
import importlib
import os
import re
import stat
import subprocess  # nosec B404
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Protocol

from reconforge.infrastructure.postgres_backup import PostgresBackupError, PostgresNativeBackupAdapter
from reconforge.upgrade.orchestrator import ApplyReceipt, PreflightEvidence, StepKind, UpgradeError, UpgradeStep

_REVISION_RE = re.compile(r"^[0-9]{4}_[a-z0-9_]{1,100}$")
_DIAGNOSTIC_LIMIT = 4000


class PostgresMigrationRunner(Protocol):
    def current_revision(self, database: Literal["source", "compatibility"]) -> str: ...
    def upgrade(self, database: Literal["source", "compatibility"], revision: str) -> None: ...
    def downgrade(self, database: Literal["source", "compatibility"], revision: str) -> None: ...


class PsycopgAlembicMigrationRunner:
    """Run fixed Alembic commands while keeping PostgreSQL credentials out of argv."""

    def __init__(
        self,
        *,
        source_dsn: str,
        compatibility_dsn: str,
        python_executable: Path,
        alembic_ini: Path,
        timeout_seconds: int = 1800,
    ) -> None:
        self._dsns = {"source": source_dsn.strip(), "compatibility": compatibility_dsn.strip()}
        if any(not value.startswith(("postgres://", "postgresql://", "postgresql+")) for value in self._dsns.values()):
            raise UpgradeError("postgres_upgrade_dsn_invalid")
        self._python = self._ordinary_file(python_executable, "python")
        self._alembic_ini = self._ordinary_file(alembic_ini, "alembic configuration")
        if timeout_seconds < 1 or timeout_seconds > 86_400:
            raise UpgradeError("postgres_upgrade_timeout_invalid")
        self._timeout = timeout_seconds

    def current_revision(self, database: Literal["source", "compatibility"]) -> str:
        try:
            psycopg = importlib.import_module("psycopg")
            with psycopg.connect(self._dsns[database]) as connection:
                row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        except Exception as exc:
            raise UpgradeError("postgres_upgrade_revision_read_failed") from exc
        if row is None or not isinstance(row[0], str) or _REVISION_RE.fullmatch(row[0]) is None:
            raise UpgradeError("postgres_upgrade_revision_invalid")
        return row[0]

    def upgrade(self, database: Literal["source", "compatibility"], revision: str) -> None:
        self._run(database, "upgrade", revision)

    def downgrade(self, database: Literal["source", "compatibility"], revision: str) -> None:
        self._run(database, "downgrade", revision)

    def _run(self, database: Literal["source", "compatibility"], operation: str, revision: str) -> None:
        if operation not in {"upgrade", "downgrade"} or _REVISION_RE.fullmatch(revision) is None:
            raise UpgradeError("postgres_upgrade_command_invalid")
        environment = os.environ.copy()
        environment["RECONFORGE_POSTGRES_DSN"] = self._dsns[database]
        try:
            with tempfile.TemporaryFile() as output:
                completed = subprocess.run(  # nosec B603
                    (self._python, "-m", "alembic", "-c", self._alembic_ini, operation, revision),
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=output,
                    env=environment,
                    shell=False,
                    check=False,
                    timeout=self._timeout,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            raise UpgradeError("postgres_upgrade_migration_process_failed") from exc
        if completed.returncode != 0:
            output.seek(0)
            raw_diagnostic = output.read()
            diagnostic = raw_diagnostic.decode("utf-8", errors="replace") if isinstance(raw_diagnostic, bytes) else str(raw_diagnostic)
            for dsn in self._dsns.values():
                diagnostic = diagnostic.replace(dsn, "[redacted-dsn]")
            diagnostic = diagnostic.strip()
            if len(diagnostic) > _DIAGNOSTIC_LIMIT:
                diagnostic = diagnostic[-_DIAGNOSTIC_LIMIT:]
            suffix = f": {diagnostic}" if diagnostic else ""
            raise UpgradeError(f"postgres_upgrade_migration_failed{suffix}")

    @staticmethod
    def _ordinary_file(path: Path, label: str) -> str:
        if not path.is_absolute():
            raise UpgradeError(f"postgres_upgrade_{label.replace(' ', '_')}_path_invalid")
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise UpgradeError(f"postgres_upgrade_{label.replace(' ', '_')}_path_invalid") from exc
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
            raise UpgradeError(f"postgres_upgrade_{label.replace(' ', '_')}_path_invalid")
        return str(path.resolve(strict=True))


def _revision_digest(revision: str) -> str:
    return hashlib.sha256(f"reconforge-postgresql-alembic:{revision}".encode("ascii")).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PostgreSQLUpgradeAdapter:
    """Drill on an isolated restore before applying a supported Alembic transition."""

    kind: StepKind = "database"

    def __init__(
        self,
        *,
        resource_id: str,
        backup: PostgresNativeBackupAdapter,
        migration_runner: PostgresMigrationRunner,
        supported_versions: Mapping[str, str],
        recovery_dir: Path,
        backup_key: bytes,
    ) -> None:
        self.resource_id = resource_id
        self._backup = backup
        self._migrations = migration_runner
        self._versions = dict(supported_versions)
        if not self._versions or any(_REVISION_RE.fullmatch(value) is None for value in self._versions.values()):
            raise UpgradeError("postgres_upgrade_supported_versions_invalid")
        if not isinstance(backup_key, bytes) or len(backup_key) != 32:
            raise UpgradeError("postgres_upgrade_backup_key_invalid")
        self._key = backup_key
        recovery_dir.mkdir(parents=True, exist_ok=True)
        self._recovery = recovery_dir.resolve(strict=True)
        if self._recovery.is_symlink() or not self._recovery.is_dir():
            raise UpgradeError("postgres_upgrade_recovery_path_invalid")

    def preflight(self, step: UpgradeStep) -> PreflightEvidence:
        source_revision, target_revision = self._validate_step(step)
        if self._migrations.current_revision("source") != source_revision:
            raise UpgradeError("postgres_upgrade_source_revision_mismatch")
        if step.target_sha256 != _revision_digest(target_revision):
            raise UpgradeError("postgres_upgrade_target_digest_mismatch")
        artifact = self._artifact(step)
        restored = False
        try:
            if not artifact.exists():
                self._backup.create_backup(artifact, key=self._key)
            elif artifact.is_symlink() or not artifact.is_file():
                raise UpgradeError("postgres_upgrade_backup_conflict")
            self._backup.restore_backup(artifact, key=self._key)
            restored = True
            if self._migrations.current_revision("compatibility") != source_revision:
                raise UpgradeError("postgres_upgrade_restore_revision_mismatch")
            self._migrations.upgrade("compatibility", target_revision)
            if self._migrations.current_revision("compatibility") != target_revision:
                raise UpgradeError("postgres_upgrade_compatibility_verification_failed")
        except Exception as exc:
            raise UpgradeError("postgres_upgrade_compatibility_drill_failed") from exc
        finally:
            if restored:
                try:
                    self._backup.drop_restored_database()
                except PostgresBackupError as exc:
                    raise UpgradeError("postgres_upgrade_compatibility_cleanup_failed") from exc
        source_digest = _revision_digest(source_revision)
        return PreflightEvidence(source_digest, source_digest, _revision_digest(target_revision))

    def apply(self, step: UpgradeStep, evidence: PreflightEvidence) -> ApplyReceipt:
        source_revision, target_revision = self._validate_step(step)
        if self._migrations.current_revision("source") != source_revision or evidence.source_digest != _revision_digest(source_revision):
            raise UpgradeError("postgres_upgrade_state_changed_after_preflight")
        self._migrations.upgrade("source", target_revision)
        return ApplyReceipt(_revision_digest(target_revision), self._rollback_token(step))

    def recover(self, step: UpgradeStep, evidence: PreflightEvidence) -> ApplyReceipt | Literal["not_applied"] | None:
        source_revision, target_revision = self._validate_step(step)
        current = self._migrations.current_revision("source")
        if current == source_revision:
            return "not_applied"
        if current == target_revision and self._artifact(step).is_file():
            return ApplyReceipt(evidence.compatibility_digest, self._rollback_token(step))
        return None

    def verify(self, step: UpgradeStep, receipt: ApplyReceipt) -> str:
        _source_revision, target_revision = self._validate_step(step)
        if receipt.rollback_token != self._rollback_token(step):
            raise UpgradeError("postgres_upgrade_verification_failed")
        if self._migrations.current_revision("source") != target_revision or receipt.output_digest != _revision_digest(target_revision):
            raise UpgradeError("postgres_upgrade_verification_failed")
        return receipt.output_digest

    def rollback(self, step: UpgradeStep, receipt: ApplyReceipt) -> str:
        source_revision, target_revision = self._validate_step(step)
        if receipt.rollback_token != self._rollback_token(step):
            raise UpgradeError("postgres_upgrade_rollback_artifact_missing")
        if self._migrations.current_revision("source") != target_revision:
            raise UpgradeError("postgres_upgrade_rollback_state_invalid")
        self._migrations.downgrade("source", source_revision)
        if self._migrations.current_revision("source") != source_revision:
            raise UpgradeError("postgres_upgrade_rollback_verification_failed")
        return _revision_digest(source_revision)

    def _artifact(self, step: UpgradeStep) -> Path:
        return self._recovery / f"{self.resource_id}-{step.from_version}-to-{step.to_version}.rfpgbackup"

    def _rollback_token(self, step: UpgradeStep) -> str:
        artifact = self._artifact(step)
        if artifact.is_symlink() or not artifact.is_file():
            raise UpgradeError("postgres_upgrade_rollback_artifact_missing")
        return f"{artifact.name}:{_file_digest(artifact)}"

    def _validate_step(self, step: UpgradeStep) -> tuple[str, str]:
        if step.kind != self.kind or step.resource_id != self.resource_id:
            raise UpgradeError("postgres_upgrade_step_identity_mismatch")
        if step.compatibility_reader != "postgres-alembic-restore-v1":
            raise UpgradeError("postgres_upgrade_compatibility_reader_unsupported")
        source = self._versions.get(step.from_version)
        target = self._versions.get(step.to_version)
        if source is None or target is None or source == target:
            raise UpgradeError("postgres_upgrade_version_transition_unsupported")
        return source, target


postgres_revision_digest = _revision_digest
