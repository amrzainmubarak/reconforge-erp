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
    _create_isolated_target_sql,
    _encrypt_dump,
    _fence_isolated_target_access_sql,
)
from reconforge.infrastructure.postgres_operations import POSTGRES_MIGRATION_REVISIONS

KEY = bytes(range(32))
COMPATIBILITY_RECOVERY_PROFILE = "team-synthetic"
COMPATIBILITY_ALEMBIC_REVISION = "0103_pg_outbox_fencing"
CURRENT_HEAD_RECOVERY_PROFILE = "team-current-head"


class _Runner:
    def __init__(
        self,
        *,
        fail_restore: bool = False,
        fail_verification: bool = False,
        fail_security_definer_hardening: bool = False,
        fail_target_access_fencing: bool = False,
        fail_source_profile: bool = False,
        fail_restore_profile: bool = False,
        fail_rollback: bool = False,
        omit_dump_attempts: int = 0,
        fail_dump_attempts: int = 0,
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail_restore = fail_restore
        self.fail_verification = fail_verification
        self.fail_security_definer_hardening = fail_security_definer_hardening
        self.fail_target_access_fencing = fail_target_access_fencing
        self.fail_source_profile = fail_source_profile
        self.fail_restore_profile = fail_restore_profile
        self.fail_rollback = fail_rollback
        self.omit_dump_attempts = omit_dump_attempts
        self.fail_dump_attempts = fail_dump_attempts

    def run(self, argv: Sequence[str], *, timeout_seconds: int) -> int:
        assert timeout_seconds == 30
        call = tuple(argv)
        self.calls.append(call)
        executable = Path(call[0]).stem
        if executable == "pg_dump":
            if self.fail_dump_attempts:
                self.fail_dump_attempts -= 1
                return 1
            if self.omit_dump_attempts:
                self.omit_dump_attempts -= 1
            else:
                if "--file" in call:
                    output = Path(call[call.index("--file") + 1])
                elif any(argument.startswith("--file=") for argument in call):
                    for argument in call:
                        if argument.startswith("--file="):
                            output = Path(argument.split("=", 1)[1])
                            break
                else:
                    short_file_index = call.index("-f")
                    output = Path(call[short_file_index + 1])
                output.write_bytes(b"PGDMP\x01\x0f confidential-database-content")
        if executable == "pg_restore" and "--list" not in call and self.fail_restore:
            return 1
        if executable == "psql":
            database = call[call.index("--dbname") + 1]
            query = call[-1]
            if self.fail_target_access_fencing and "REVOKE CONNECT ON DATABASE" in query:
                return 1
            if self.fail_security_definer_hardening and "REVOKE ALL ON %s" in query:
                return 1
            if self.fail_verification and "SELECT 1 /" in query:
                return 1
            if database == "service=reconforge_source" and self.fail_source_profile:
                return 1
            if database.startswith("service=reconforge_admin ") and self.fail_restore_profile:
                return 1
        if executable == "dropdb" and self.fail_rollback:
            return 1
        return 0


class _StdoutFallbackRunner(_Runner):
    """Simulate a client wrapper that streams a successful dump to stdout."""

    def run_to_file(self, argv: Sequence[str], output_path: Path, *, timeout_seconds: int) -> int:
        assert timeout_seconds == 30
        self.calls.append(tuple(argv))
        output_path.write_bytes(b"PGDMP\x01\x0f streamed-database-content")
        return 0


def _tools(tmp_path: Path) -> PostgresNativeTools:
    tmp_path.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name in ("pg_dump", "pg_restore", "createdb", "dropdb", "psql"):
        path = tmp_path / name
        path.write_bytes(b"tool")
        paths[name] = path.resolve()
    return PostgresNativeTools(**paths)


def _adapter(
    tmp_path: Path,
    runner: _Runner,
    *,
    recovery_profile: str = COMPATIBILITY_RECOVERY_PROFILE,
    expected_alembic_revision: str = COMPATIBILITY_ALEMBIC_REVISION,
) -> PostgresNativeBackupAdapter:
    return PostgresNativeBackupAdapter(
        PostgresBackupSettings(
            source_service="reconforge_source",
            maintenance_service="reconforge_admin",
            restore_database="reconforge_restore_drill",
            recovery_profile=recovery_profile,
            expected_alembic_revision=expected_alembic_revision,
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
    assert f'"recovery_profile":"{COMPATIBILITY_RECOVERY_PROFILE}"'.encode("ascii") in raw
    assert f'"alembic_revision":"{COMPATIBILITY_ALEMBIC_REVISION}"'.encode("ascii") in raw
    assert Path(runner.calls[0][0]).stem == "psql"
    assert "service=reconforge_source" in runner.calls[0]
    assert f"reconforge_expected_revision={COMPATIBILITY_ALEMBIC_REVISION}" in runner.calls[0]
    assert ":'reconforge_expected_revision'" in runner.calls[0][-1]
    dump_call = next(call for call in runner.calls if Path(call[0]).stem == "pg_dump")
    assert dump_call[1:] == (
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        dump_call[5],
        "--dbname",
        "service=reconforge_source",
    )
    assert all("password" not in value.casefold() for call in runner.calls for value in call)


def test_backup_refuses_a_source_outside_the_configured_recovery_profile(tmp_path: Path) -> None:
    runner = _Runner(fail_source_profile=True)
    output = tmp_path / "unverified-source.rfpgbackup"

    with pytest.raises(PostgresBackupError, match="source profile verification failed"):
        _adapter(tmp_path, runner).create_backup(output, key=KEY)

    assert not output.exists()
    assert [Path(call[0]).stem for call in runner.calls] == ["psql"]


@pytest.fixture
def current_head_recovery_profile() -> tuple[str, str]:
    """Derive the mock recovery contract from the PostgreSQL migration head."""

    return CURRENT_HEAD_RECOVERY_PROFILE, POSTGRES_MIGRATION_REVISIONS[-1]


def test_current_head_profile_binds_and_rejects_0103_before_restore_actions(
    tmp_path: Path,
    current_head_recovery_profile: tuple[str, str],
) -> None:
    recovery_profile, expected_alembic_revision = current_head_recovery_profile
    artifact = tmp_path / "current-head.rfpgbackup"
    create_runner = _Runner()

    _adapter(
        tmp_path / "create-tools",
        create_runner,
        recovery_profile=recovery_profile,
        expected_alembic_revision=expected_alembic_revision,
    ).create_backup(artifact, key=KEY)

    raw = artifact.read_bytes()
    assert f'"recovery_profile":"{recovery_profile}"'.encode("ascii") in raw
    assert f'"alembic_revision":"{expected_alembic_revision}"'.encode("ascii") in raw
    assert f"reconforge_expected_revision={expected_alembic_revision}" in create_runner.calls[0]

    restore_runner = _Runner()
    with pytest.raises(PostgresBackupError, match="does not match the configured recovery profile"):
        _adapter(
            tmp_path / "restore-tools",
            restore_runner,
            recovery_profile=recovery_profile,
            expected_alembic_revision=COMPATIBILITY_ALEMBIC_REVISION,
        ).restore_backup(artifact, key=KEY)

    assert restore_runner.calls == []


@pytest.mark.parametrize(
    ("recovery_profile", "expected_alembic_revision"),
    [
        ("other-profile", COMPATIBILITY_ALEMBIC_REVISION),
        (COMPATIBILITY_RECOVERY_PROFILE, "0102_pg_budget_control"),
    ],
)
def test_restore_rejects_a_bound_artifact_for_another_recovery_profile_before_target_mutation(
    tmp_path: Path,
    recovery_profile: str,
    expected_alembic_revision: str,
) -> None:
    artifact = tmp_path / "bound.rfpgbackup"
    _adapter(tmp_path / "create-tools", _Runner()).create_backup(artifact, key=KEY)
    restore_runner = _Runner()

    with pytest.raises(PostgresBackupError, match="does not match the configured recovery profile"):
        _adapter(
            tmp_path / "restore-tools",
            restore_runner,
            recovery_profile=recovery_profile,
            expected_alembic_revision=expected_alembic_revision,
        ).restore_backup(artifact, key=KEY)

    assert restore_runner.calls == []


def test_legacy_unbound_artifact_remains_readable_but_must_pass_target_revision_gate(tmp_path: Path) -> None:
    dump = tmp_path / "legacy.dump"
    dump.write_bytes(b"PGDMP\x01\x0f legacy-database-content")
    artifact = tmp_path / "legacy.rfpgbackup"
    _encrypt_dump(dump, artifact, KEY)
    runner = _Runner()

    outcome = _adapter(tmp_path / "restore-tools", runner).restore_backup(artifact, key=KEY)

    assert outcome.target == "reconforge_restore_drill"
    assert [Path(call[0]).stem for call in runner.calls] == [
        "pg_restore",
        "psql",
        "psql",
        "pg_restore",
        "psql",
        "psql",
    ]
    assert f"reconforge_expected_revision={COMPATIBILITY_ALEMBIC_REVISION}" in runner.calls[-1]


def test_restore_rehardens_security_definer_routines_before_profile_verification(tmp_path: Path) -> None:
    artifact = tmp_path / "security-definer.rfpgbackup"
    _adapter(tmp_path / "create-tools", _Runner()).create_backup(artifact, key=KEY)
    runner = _Runner()

    _adapter(tmp_path / "restore-tools", runner).restore_backup(artifact, key=KEY)

    psql_calls = [call for call in runner.calls if Path(call[0]).stem == "psql"]
    assert len(psql_calls) == 4
    creation_query, access_fence_query, hardening_query, verification_query = (
        call[-1] for call in psql_calls
    )
    assert creation_query == 'CREATE DATABASE "reconforge_restore_drill" WITH ALLOW_CONNECTIONS false;'
    assert access_fence_query == (
        "BEGIN;\n"
        'ALTER DATABASE "reconforge_restore_drill" ALLOW_CONNECTIONS true;\n'
        'REVOKE CONNECT ON DATABASE "reconforge_restore_drill" FROM PUBLIC;\n'
        "COMMIT;"
    )
    assert "pg_catalog.pg_proc" in hardening_query
    assert "procedure.prosecdef" in hardening_query
    assert "procedure.prokind IN ('f', 'p')" in hardening_query
    assert "REVOKE ALL ON %s %I.%I(%s) FROM PUBLIC" in hardening_query
    assert "FUNCTION" in hardening_query
    assert "PROCEDURE" in hardening_query
    assert "SELECT 1 /" in verification_query


def test_failed_security_definer_hardening_rolls_back_isolated_target(tmp_path: Path) -> None:
    artifact = tmp_path / "security-definer-failure.rfpgbackup"
    _adapter(tmp_path / "create-tools", _Runner()).create_backup(artifact, key=KEY)
    runner = _Runner(fail_security_definer_hardening=True)

    with pytest.raises(PostgresBackupError, match="security-definer hardening failed"):
        _adapter(tmp_path / "restore-tools", runner).restore_backup(artifact, key=KEY)

    assert [Path(call[0]).stem for call in runner.calls] == [
        "pg_restore",
        "psql",
        "psql",
        "pg_restore",
        "psql",
        "dropdb",
    ]


def test_failed_target_access_fencing_rolls_back_non_connectable_target(tmp_path: Path) -> None:
    artifact = tmp_path / "target-access-fence.rfpgbackup"
    _adapter(tmp_path / "create-tools", _Runner()).create_backup(artifact, key=KEY)
    runner = _Runner(fail_target_access_fencing=True)

    with pytest.raises(PostgresBackupError, match="target access fencing failed"):
        _adapter(tmp_path / "restore-tools", runner).restore_backup(artifact, key=KEY)

    assert [Path(call[0]).stem for call in runner.calls] == [
        "pg_restore",
        "psql",
        "psql",
        "dropdb",
    ]
    assert runner.calls[1][-1] == 'CREATE DATABASE "reconforge_restore_drill" WITH ALLOW_CONNECTIONS false;'
    assert "REVOKE CONNECT ON DATABASE \"reconforge_restore_drill\" FROM PUBLIC" in runner.calls[2][-1]


def test_legacy_settings_remain_compatible_for_unbound_artifacts(tmp_path: Path) -> None:
    runner = _Runner()
    adapter = PostgresNativeBackupAdapter(
        PostgresBackupSettings(
            source_service="reconforge_source",
            maintenance_service="reconforge_admin",
            restore_database="reconforge_restore_drill",
            tools=_tools(tmp_path / "tools"),
            timeout_seconds=30,
        ),
        runner=runner,
    )
    artifact = tmp_path / "legacy-settings.rfpgbackup"

    adapter.create_backup(artifact, key=KEY)
    outcome = adapter.restore_backup(artifact, key=KEY)

    assert outcome.target == "reconforge_restore_drill"
    assert b'"recovery_profile"' not in artifact.read_bytes()


def test_legacy_settings_refuse_a_bound_artifact_before_target_mutation(tmp_path: Path) -> None:
    artifact = tmp_path / "bound-for-legacy.rfpgbackup"
    _adapter(tmp_path / "create-tools", _Runner()).create_backup(artifact, key=KEY)
    runner = _Runner()
    adapter = PostgresNativeBackupAdapter(
        PostgresBackupSettings(
            source_service="reconforge_source",
            maintenance_service="reconforge_admin",
            restore_database="reconforge_restore_drill",
            tools=_tools(tmp_path / "legacy-tools"),
            timeout_seconds=30,
        ),
        runner=runner,
    )

    with pytest.raises(PostgresBackupError, match="requires a configured recovery profile"):
        adapter.restore_backup(artifact, key=KEY)

    assert runner.calls == []


def test_recovery_profile_and_expected_revision_are_an_atomic_settings_pair(tmp_path: Path) -> None:
    with pytest.raises(PostgresBackupError, match="configured together"):
        PostgresBackupSettings(
            source_service="reconforge_source",
            maintenance_service="reconforge_admin",
            restore_database="reconforge_restore_drill",
            tools=_tools(tmp_path),
            recovery_profile="team-synthetic",
        )


def test_backup_retries_portable_file_argument_when_success_has_no_dump(tmp_path: Path) -> None:
    runner = _Runner(omit_dump_attempts=1)
    adapter = _adapter(tmp_path, runner)

    result = adapter.create_backup(tmp_path / "portable-retry.rfpgbackup", key=KEY)

    dump_calls = [call for call in runner.calls if Path(call[0]).stem == "pg_dump"]
    assert len(dump_calls) == 2
    assert dump_calls[0][1:] == (
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        dump_calls[0][5],
        "--dbname",
        "service=reconforge_source",
    )
    assert any(
        argument == "-f" or argument.startswith("--file=")
        for argument in dump_calls[1]
    )
    assert len(dump_calls[1]) in {7, 8}
    assert result.bytes_written > 0


def test_backup_retries_to_equals_form_when_short_form_still_has_no_dump(tmp_path: Path) -> None:
    runner = _Runner(omit_dump_attempts=2)
    adapter = _adapter(tmp_path, runner)

    result = adapter.create_backup(tmp_path / "portable-retry-equals.rfpgbackup", key=KEY)

    dump_calls = [call for call in runner.calls if Path(call[0]).stem == "pg_dump"]
    assert len(dump_calls) == 3
    assert "--file" in dump_calls[0]
    assert any(argument == "-f" for argument in dump_calls[1])
    assert any(argument.startswith("--file=") for argument in dump_calls[2])
    assert result.bytes_written > 0


def test_backup_retries_to_next_form_when_command_invocation_fails(tmp_path: Path) -> None:
    # Some environments expose pg_dump binaries where a specific syntax form fails,
    # even though a fallback form succeeds.
    runner = _Runner(fail_dump_attempts=2)
    adapter = _adapter(tmp_path, runner)

    result = adapter.create_backup(tmp_path / "invocation-failover.rfpgbackup", key=KEY)

    dump_calls = [call for call in runner.calls if Path(call[0]).stem == "pg_dump"]
    assert len(dump_calls) == 3
    assert result.bytes_written > 0


def test_backup_fails_closed_when_portable_retry_still_has_no_dump(tmp_path: Path) -> None:
    runner = _Runner(omit_dump_attempts=3)

    with pytest.raises(
        PostgresBackupError,
        match="no usable dump after all attempts",
    ):
        _adapter(tmp_path, runner).create_backup(tmp_path / "missing.rfpgbackup", key=KEY)


def test_backup_fails_closed_with_no_stdout_fallback_runner_when_all_file_forms_fail(tmp_path: Path) -> None:
    class _NoStdoutFallbackRunner(_Runner):
        """Runner intentionally lacks run_to_file to emulate restricted wrappers."""

    runner = _NoStdoutFallbackRunner(omit_dump_attempts=3)

    with pytest.raises(
        PostgresBackupError,
        match="stdout fallback path was unavailable",
    ):
        _adapter(tmp_path, runner).create_backup(tmp_path / "fallback-missing.rfpgbackup", key=KEY)


def test_backup_uses_native_stdout_fallback_after_file_forms_produce_no_dump(tmp_path: Path) -> None:
    runner = _StdoutFallbackRunner(omit_dump_attempts=3)

    result = _adapter(tmp_path, runner).create_backup(tmp_path / "stdout-fallback.rfpgbackup", key=KEY)

    assert result.bytes_written > 0
    dump_calls = [call for call in runner.calls if Path(call[0]).stem == "pg_dump"]
    assert len(dump_calls) == 4
    assert dump_calls[-1][1:] == (
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--dbname",
        "service=reconforge_source",
    )


def test_restore_fences_target_access_before_restore_and_rolls_back_partial_target(tmp_path: Path) -> None:
    create_runner = _Runner()
    output = tmp_path / "postgres.rfpgbackup"
    _adapter(tmp_path / "create-tools", create_runner).create_backup(output, key=KEY)

    restore_runner = _Runner(fail_restore=True)
    adapter = _adapter(tmp_path / "restore-tools", restore_runner)
    with pytest.raises(PostgresBackupError, match="restore failed"):
        adapter.restore_backup(output, key=KEY)

    commands = [Path(call[0]).stem for call in restore_runner.calls]
    assert commands == ["pg_restore", "psql", "psql", "pg_restore", "dropdb"]
    assert restore_runner.calls[1][1:] == (
        "--no-psqlrc",
        "--set",
        "ON_ERROR_STOP=1",
        "--dbname",
        "service=reconforge_admin",
        "--command",
        'CREATE DATABASE "reconforge_restore_drill" WITH ALLOW_CONNECTIONS false;',
    )
    assert "REVOKE CONNECT ON DATABASE \"reconforge_restore_drill\" FROM PUBLIC" in restore_runner.calls[2][-1]
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
        "psql",
        "psql",
        "pg_restore",
        "psql",
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


def test_profile_binding_is_authenticated_before_any_restore_command(tmp_path: Path) -> None:
    artifact = tmp_path / "bound-profile.rfpgbackup"
    _adapter(tmp_path / "create-tools", _Runner()).create_backup(artifact, key=KEY)
    raw = bytearray(artifact.read_bytes())
    profile = b"team-synthetic"
    profile_offset = raw.find(profile)
    assert profile_offset >= 0
    raw[profile_offset : profile_offset + len(profile)] = b"evil-profile-1"
    artifact.write_bytes(raw)
    runner = _Runner()

    with pytest.raises(PostgresBackupError, match="authentication"):
        _adapter(tmp_path / "restore-tools", runner).restore_backup(artifact, key=KEY)

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
                recovery_profile=COMPATIBILITY_RECOVERY_PROFILE,
                expected_alembic_revision=COMPATIBILITY_ALEMBIC_REVISION,
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
            recovery_profile=COMPATIBILITY_RECOVERY_PROFILE,
            expected_alembic_revision=COMPATIBILITY_ALEMBIC_REVISION,
            tools=_tools(tmp_path),
        )
    with pytest.raises(PostgresBackupError, match="Recovery profile"):
        PostgresBackupSettings(
            source_service="source",
            maintenance_service="admin",
            restore_database="restore_db",
            recovery_profile="profile with spaces",
            expected_alembic_revision=COMPATIBILITY_ALEMBIC_REVISION,
            tools=_tools(tmp_path),
        )
    with pytest.raises(PostgresBackupError, match="Alembic revision"):
        PostgresBackupSettings(
            source_service="source",
            maintenance_service="admin",
            restore_database="restore_db",
            recovery_profile=COMPATIBILITY_RECOVERY_PROFILE,
            expected_alembic_revision="0103;drop",
            tools=_tools(tmp_path),
        )


_LIVE_BACKUP_ENV = (
    "RECONFORGE_TEST_POSTGRES_SOURCE_SERVICE",
    "RECONFORGE_TEST_POSTGRES_MAINTENANCE_SERVICE",
)
_LIVE_ACCESS_FENCE_ENV = "RECONFORGE_TEST_POSTGRES_ADMIN_DSN"


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


@pytest.mark.skipif(
    not os.environ.get(_LIVE_ACCESS_FENCE_ENV),
    reason="requires an owned PostgreSQL administrator DSN",
)
def test_live_postgres_restore_target_access_fence_blocks_runtime_role() -> None:
    """The target is never PUBLIC-connectable before restore ownership takes effect."""

    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql

    admin_parameters = psycopg.conninfo.conninfo_to_dict(os.environ[_LIVE_ACCESS_FENCE_ENV])
    if not admin_parameters.get("user") or not admin_parameters.get("host"):
        pytest.skip("requires a complete owned PostgreSQL administrator DSN")
    suffix = uuid4().hex[:12]
    database_name = "reconforge_restore_fence_" + suffix
    runtime_role = "rf_restore_runtime_" + suffix
    runtime_password = uuid4().hex + uuid4().hex
    control_dsn = psycopg.conninfo.make_conninfo(
        **{**admin_parameters, "dbname": "postgres", "connect_timeout": "5"}
    )
    runtime_dsn = psycopg.conninfo.make_conninfo(
        **{
            **admin_parameters,
            "dbname": database_name,
            "user": runtime_role,
            "password": runtime_password,
            "connect_timeout": "5",
        }
    )
    owner_dsn = psycopg.conninfo.make_conninfo(
        **{**admin_parameters, "dbname": database_name, "connect_timeout": "5"}
    )
    created_role = False
    created_database = False
    try:
        with psycopg.connect(control_dsn, autocommit=True) as administrator:
            capabilities = administrator.execute(
                """
                SELECT rolsuper OR (rolcreaterole AND rolcreatedb)
                FROM pg_catalog.pg_roles
                WHERE rolname=current_user
                """
            ).fetchone()
            if capabilities != (True,):
                pytest.skip("requires an owned PostgreSQL administrator with CREATEROLE and CREATEDB")
            administrator.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"
                ).format(sql.Identifier(runtime_role), sql.Literal(runtime_password))
            )
            created_role = True
            administrator.execute(_create_isolated_target_sql(database_name))
            created_database = True

            with pytest.raises(psycopg.OperationalError):
                psycopg.connect(runtime_dsn).close()
            with pytest.raises(psycopg.OperationalError):
                psycopg.connect(owner_dsn).close()

            administrator.execute(_fence_isolated_target_access_sql(database_name))

        with psycopg.connect(owner_dsn) as owner:
            assert owner.execute("SELECT current_database()").fetchone() == (database_name,)
        with pytest.raises(psycopg.OperationalError):
            psycopg.connect(runtime_dsn).close()
    finally:
        with psycopg.connect(control_dsn, autocommit=True) as administrator:
            if created_database:
                administrator.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database_name))
                )
            if created_role:
                administrator.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(runtime_role)))


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
        recovery_profile="live-postgres-current-head-drill",
        expected_alembic_revision=POSTGRES_MIGRATION_REVISIONS[-1],
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
