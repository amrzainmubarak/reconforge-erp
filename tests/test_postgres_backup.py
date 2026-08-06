from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.application.backup_restore import (
    BACKUP_CREATE_PERMISSION,
    RESTORE_EXECUTE_PERMISSION,
    BackupRestoreApplicationService,
    BackupRestoreAuthorizationError,
)
from reconforge.auth.policy import PolicyEvaluationContext
from reconforge.infrastructure.postgres_backup import (
    NativeCommandRunner,
    PostgresBackupError,
    PostgresBackupSettings,
    PostgresNativeBackupAdapter,
    PostgresNativeTools,
)

KEY = bytes(range(32))


class _Runner:
    def __init__(
        self,
        *,
        fail_restore: bool = False,
        fail_verification: bool = False,
        fail_rollback: bool = False,
        omit_dump_attempts: int = 0,
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail_restore = fail_restore
        self.fail_verification = fail_verification
        self.fail_rollback = fail_rollback
        self.omit_dump_attempts = omit_dump_attempts

    def run(self, argv: Sequence[str], *, timeout_seconds: int) -> int:
        assert timeout_seconds == 30
        call = tuple(argv)
        self.calls.append(call)
        executable = Path(call[0]).stem
        if executable == "pg_dump":
            if self.omit_dump_attempts:
                self.omit_dump_attempts -= 1
            else:
                output = Path(call[call.index("--file") + 1]) if "--file" in call else Path(call[4].split("=", 1)[1])
                output.write_bytes(b"PGDMP\x01\x0f confidential-database-content")
        if executable == "pg_restore" and "--list" not in call and self.fail_restore:
            return 1
        if executable == "psql" and self.fail_verification:
            return 1
        if executable == "dropdb" and self.fail_rollback:
            return 1
        return 0


def _tools(tmp_path: Path) -> PostgresNativeTools:
    tmp_path.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name in ("pg_dump", "pg_restore", "createdb", "dropdb", "psql"):
        path = tmp_path / name
        path.write_bytes(b"tool")
        paths[name] = path.resolve()
    return PostgresNativeTools(**paths)


def _adapter(tmp_path: Path, runner: _Runner) -> PostgresNativeBackupAdapter:
    return PostgresNativeBackupAdapter(
        PostgresBackupSettings(
            source_service="reconforge_source",
            maintenance_service="reconforge_admin",
            restore_database="reconforge_restore_drill",
            tools=_tools(tmp_path),
            timeout_seconds=30,
        ),
        runner=runner,
    )


def _context(permission: str | None) -> PolicyEvaluationContext:
    return PolicyEvaluationContext(
        user_id="operator-1",
        username="operator",
        user_permissions=set() if permission is None else {permission},
    )


def test_postgres_native_backup_is_encrypted_and_uses_service_not_secret(tmp_path: Path) -> None:
    runner = _Runner()
    adapter = _adapter(tmp_path, runner)
    output = tmp_path / "postgres.rfpgbackup"

    result = adapter.create_backup(output, key=KEY)

    raw = output.read_bytes()
    assert result.backend == "postgresql"
    assert result.bytes_written == len(raw)
    assert b"confidential-database-content" not in raw
    assert runner.calls[0][1:] == (
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        runner.calls[0][5],
        "--dbname",
        "service=reconforge_source",
    )
    assert all("password" not in value.casefold() for value in runner.calls[0])


def test_backup_retries_portable_file_argument_when_success_has_no_dump(tmp_path: Path) -> None:
    runner = _Runner(omit_dump_attempts=1)
    adapter = _adapter(tmp_path, runner)

    result = adapter.create_backup(tmp_path / "portable-retry.rfpgbackup", key=KEY)

    dump_calls = [call for call in runner.calls if Path(call[0]).stem == "pg_dump"]
    assert len(dump_calls) == 2
    assert "--file" in dump_calls[0]
    assert any(argument.startswith("--file=") for argument in dump_calls[1])
    assert result.bytes_written > 0


def test_backup_fails_closed_when_portable_retry_still_has_no_dump(tmp_path: Path) -> None:
    runner = _Runner(omit_dump_attempts=2)

    with pytest.raises(PostgresBackupError, match="no usable dump after retry"):
        _adapter(tmp_path, runner).create_backup(tmp_path / "missing.rfpgbackup", key=KEY)


def test_restore_creates_new_database_and_rollback_removes_partial_target(tmp_path: Path) -> None:
    create_runner = _Runner()
    output = tmp_path / "postgres.rfpgbackup"
    _adapter(tmp_path / "create-tools", create_runner).create_backup(output, key=KEY)

    restore_runner = _Runner(fail_restore=True)
    adapter = _adapter(tmp_path / "restore-tools", restore_runner)
    with pytest.raises(PostgresBackupError, match="restore failed"):
        adapter.restore_backup(output, key=KEY)

    commands = [Path(call[0]).stem for call in restore_runner.calls]
    assert commands == ["pg_restore", "createdb", "pg_restore", "dropdb"]
    assert restore_runner.calls[1][1] == "--maintenance-db=service=reconforge_admin"
    assert restore_runner.calls[-1][-1] == "reconforge_restore_drill"


def test_restore_reports_failed_rollback_without_leaking_command_output(tmp_path: Path) -> None:
    output = tmp_path / "postgres.rfpgbackup"
    _adapter(tmp_path / "create-tools", _Runner()).create_backup(output, key=KEY)
    adapter = _adapter(tmp_path / "restore-tools", _Runner(fail_restore=True, fail_rollback=True))

    with pytest.raises(PostgresBackupError, match="isolate the target database") as caught:
        adapter.restore_backup(output, key=KEY)
    assert "service=" not in str(caught.value)


def test_failed_post_restore_verification_rolls_back_new_database(tmp_path: Path) -> None:
    output = tmp_path / "postgres.rfpgbackup"
    _adapter(tmp_path / "create-tools", _Runner()).create_backup(output, key=KEY)
    runner = _Runner(fail_verification=True)

    with pytest.raises(PostgresBackupError, match="verification failed"):
        _adapter(tmp_path / "restore-tools", runner).restore_backup(output, key=KEY)
    assert [Path(call[0]).stem for call in runner.calls] == [
        "pg_restore",
        "createdb",
        "pg_restore",
        "psql",
        "dropdb",
    ]


def test_explicit_restore_cleanup_targets_only_configured_isolated_database(tmp_path: Path) -> None:
    runner = _Runner()
    adapter = _adapter(tmp_path, runner)
    adapter.drop_restored_database()
    assert Path(runner.calls[0][0]).stem == "dropdb"
    assert runner.calls[0][1:] == (
        "--if-exists",
        "--maintenance-db=service=reconforge_admin",
        "reconforge_restore_drill",
    )


def test_wrong_key_and_tamper_fail_before_native_restore_calls(tmp_path: Path) -> None:
    output = tmp_path / "postgres.rfpgbackup"
    _adapter(tmp_path / "create-tools", _Runner()).create_backup(output, key=KEY)
    runner = _Runner()
    adapter = _adapter(tmp_path / "restore-tools", runner)

    with pytest.raises(PostgresBackupError, match="integrity"):
        adapter.restore_backup(output, key=b"x" * 32)
    assert runner.calls == []

    raw = bytearray(output.read_bytes())
    raw[-20] ^= 1
    output.write_bytes(raw)
    with pytest.raises(PostgresBackupError, match="authentication"):
        adapter.restore_backup(output, key=KEY)
    assert runner.calls == []


def test_application_service_denies_before_adapter_and_allows_exact_permissions(tmp_path: Path) -> None:
    runner = _Runner()
    service = BackupRestoreApplicationService(_adapter(tmp_path, runner))
    output = tmp_path / "postgres.rfpgbackup"

    with pytest.raises(BackupRestoreAuthorizationError):
        service.create_backup(_context(None), output, key=KEY)
    assert runner.calls == []

    service.create_backup(_context(BACKUP_CREATE_PERMISSION), output, key=KEY)
    restored = service.restore_backup(_context(RESTORE_EXECUTE_PERMISSION), output, key=KEY)
    assert restored.target == "reconforge_restore_drill"
    assert restored.artifact_sha256 == hashlib.sha256(output.read_bytes()).hexdigest()


def test_tool_paths_and_database_names_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(PostgresBackupError, match="absolute"):
        PostgresNativeBackupAdapter(
            PostgresBackupSettings(
                source_service="source",
                maintenance_service="admin",
                restore_database="restore_db",
                tools=PostgresNativeTools(
                    *(Path(name) for name in ("pg_dump", "pg_restore", "createdb", "dropdb", "psql"))
                ),
            )
        )
    with pytest.raises(PostgresBackupError, match="database name"):
        PostgresBackupSettings(
            source_service="source",
            maintenance_service="admin",
            restore_database="postgres;drop",
            tools=_tools(tmp_path),
        )


_LIVE_BACKUP_ENV = (
    "RECONFORGE_TEST_POSTGRES_SOURCE_SERVICE",
    "RECONFORGE_TEST_POSTGRES_MAINTENANCE_SERVICE",
)


def _live_native_tools() -> PostgresNativeTools | None:
    """Resolve real versioned binaries instead of Debian's command-name-sensitive pg_wrapper."""
    names = ("pg_dump", "pg_restore", "createdb", "dropdb", "psql")
    candidates: dict[str, Path] = {}
    pg_config = shutil.which("pg_config")
    if pg_config is not None:
        completed = subprocess.run(  # nosec B603
            (pg_config, "--bindir"),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if completed.returncode == 0:
            bindir = Path(completed.stdout.strip())
            candidates = {name: bindir / name for name in names}
    if not candidates or not all(path.is_file() for path in candidates.values()):
        resolved = {name: shutil.which(name) for name in names}
        if not all(resolved.values()):
            return None
        candidates = {name: Path(path) for name, path in resolved.items() if path is not None}
    return PostgresNativeTools(**{name: path.resolve(strict=True) for name, path in candidates.items()})


def test_live_native_tools_preserve_command_identity_via_pg_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bindir = tmp_path / "versioned-bin"
    bindir.mkdir()
    names = ("pg_dump", "pg_restore", "createdb", "dropdb", "psql")
    for name in names:
        (bindir / name).write_bytes(b"native-tool")
    pg_config = tmp_path / "pg_config"
    pg_config.write_bytes(b"config-tool")

    monkeypatch.setattr(shutil, "which", lambda name: str(pg_config) if name == "pg_config" else None)

    def _pg_config_result(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        assert tuple(argv) == (str(pg_config), "--bindir")
        return subprocess.CompletedProcess(argv, 0, stdout=str(bindir), stderr="")

    monkeypatch.setattr(subprocess, "run", _pg_config_result)
    tools = _live_native_tools()

    assert tools is not None
    assert tools.validated() == tuple(str((bindir / name).resolve()) for name in names)


@pytest.mark.skipif(
    not all(os.environ.get(name) for name in _LIVE_BACKUP_ENV),
    reason="requires disposable PostgreSQL source and maintenance services",
)
def test_live_postgres_native_adapter_encrypted_backup_isolated_restore_and_cleanup(tmp_path: Path) -> None:
    tools = _live_native_tools()
    if tools is None:
        pytest.skip("requires PostgreSQL native client tools on PATH")
    maintenance = os.environ["RECONFORGE_TEST_POSTGRES_MAINTENANCE_SERVICE"]
    restore_database = "reconforge_restore_" + uuid4().hex[:20]
    settings = PostgresBackupSettings(
        source_service=os.environ["RECONFORGE_TEST_POSTGRES_SOURCE_SERVICE"],
        maintenance_service=maintenance,
        restore_database=restore_database,
        tools=tools,
        timeout_seconds=1800,
    )
    adapter = PostgresNativeBackupAdapter(settings)
    service = BackupRestoreApplicationService(adapter)
    artifact_path = tmp_path / "live-postgres.rfpgbackup"
    restored = False
    try:
        artifact = service.create_backup(_context(BACKUP_CREATE_PERMISSION), artifact_path, key=KEY)
        assert artifact.sha256 == hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        outcome = service.restore_backup(_context(RESTORE_EXECUTE_PERMISSION), artifact_path, key=KEY)
        restored = True
        assert outcome.target == restore_database
        assert outcome.artifact_sha256 == artifact.sha256
        assert outcome.rollback_performed is False
    finally:
        if restored:
            dropdb = tools.validated()[3]
            result = NativeCommandRunner().run(
                (dropdb, "--if-exists", f"--maintenance-db=service={maintenance}", restore_database),
                timeout_seconds=1800,
            )
            assert result == 0, f"isolated PostgreSQL restore database requires manual cleanup: {restore_database}"
