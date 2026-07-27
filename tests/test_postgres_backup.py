from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from reconforge.application.backup_restore import (
    BACKUP_CREATE_PERMISSION,
    RESTORE_EXECUTE_PERMISSION,
    BackupRestoreApplicationService,
    BackupRestoreAuthorizationError,
)
from reconforge.auth.policy import PolicyEvaluationContext
from reconforge.infrastructure.postgres_backup import (
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
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail_restore = fail_restore
        self.fail_verification = fail_verification
        self.fail_rollback = fail_rollback

    def run(self, argv: Sequence[str], *, timeout_seconds: int) -> int:
        assert timeout_seconds == 30
        call = tuple(argv)
        self.calls.append(call)
        executable = Path(call[0]).stem
        if executable == "pg_dump":
            output = Path(call[call.index("--file") + 1])
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
        "service=reconforge_source",
    )
    assert all("password" not in value.casefold() for value in runner.calls[0])


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
