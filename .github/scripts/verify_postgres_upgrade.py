"""Run the composed PostgreSQL 0052 -> 0053 upgrade drill in disposable Docker."""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

from reconforge.infrastructure.postgres_backup import (
    PostgresBackupSettings,
    PostgresNativeBackupAdapter,
    PostgresNativeTools,
)
from reconforge.upgrade.orchestrator import UpgradeStep
from reconforge.upgrade.postgres_adapter import (
    PostgreSQLUpgradeAdapter,
    PsycopgAlembicMigrationRunner,
    postgres_revision_digest,
)

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "postgres:17.10-alpine"
PASSWORD = "reconforge-synthetic-upgrade-only"


def _command(argv: Sequence[str], *, capture: bool = False) -> str:
    completed = subprocess.run(  # nosec B603
        tuple(argv), cwd=ROOT, shell=False, check=False, text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
        timeout=300,
    )
    if completed.returncode != 0:
        raise RuntimeError("disposable PostgreSQL command failed")
    return completed.stdout.strip() if capture else ""


class DockerPostgresRunner:
    """Translate the closed native-tool argv to the same tools inside one container."""

    def __init__(self, container: str) -> None:
        self.container = container
        self._dump_in_container = "/tmp/reconforge-upgrade.dump"

    def run(self, argv: Sequence[str], *, timeout_seconds: int) -> int:
        del timeout_seconds
        operation = Path(argv[0]).stem
        try:
            if operation == "pg_dump":
                host_dump = Path(argv[argv.index("--file") + 1])
                self._exec(("pg_dump", "-U", "postgres", "-d", "postgres", "-Fc", "-f", self._dump_in_container))
                _command(("docker", "cp", f"{self.container}:{self._dump_in_container}", str(host_dump)))
            elif operation == "pg_restore" and "--list" in argv:
                host_dump = Path(argv[-1])
                _command(("docker", "cp", str(host_dump), f"{self.container}:{self._dump_in_container}"))
                self._exec(("pg_restore", "--list", self._dump_in_container))
            elif operation == "createdb":
                self._exec(("createdb", "-U", "postgres", argv[-1]))
            elif operation == "pg_restore":
                database = str(argv[argv.index("--dbname") + 1]).split("dbname=", 1)[1]
                self._exec(("pg_restore", "--exit-on-error", "--no-owner", "--no-privileges", "-U", "postgres", "-d", database, self._dump_in_container))
            elif operation == "psql":
                database = str(argv[argv.index("--dbname") + 1]).split("dbname=", 1)[1]
                sql = argv[argv.index("--command") + 1]
                self._exec(("psql", "-U", "postgres", "-d", database, "-v", "ON_ERROR_STOP=1", "-c", sql))
            elif operation == "dropdb":
                self._exec(("dropdb", "-U", "postgres", "--if-exists", argv[-1]))
            else:
                return 1
        except (RuntimeError, OSError, ValueError, IndexError):
            return 1
        return 0

    def _exec(self, command: Sequence[str]) -> None:
        _command(("docker", "exec", "-e", f"PGPASSWORD={PASSWORD}", self.container, *command))


def _tools(directory: Path) -> PostgresNativeTools:
    directory.mkdir(parents=True, exist_ok=False)
    paths: dict[str, Path] = {}
    for name in ("pg_dump", "pg_restore", "createdb", "dropdb", "psql"):
        target = directory / f"{name}.exe"
        shutil.copy2(sys.executable, target)
        paths[name] = target.resolve(strict=True)
    return PostgresNativeTools(**paths)


def _wait(dsn: str) -> None:
    import psycopg

    for _ in range(60):
        try:
            with psycopg.connect(dsn) as connection:
                connection.execute("SELECT 1")
            return
        except psycopg.Error:
            time.sleep(0.5)
    raise RuntimeError("disposable PostgreSQL did not become ready")


def main() -> int:
    container = "reconforge-upgrade-" + os.urandom(6).hex()
    container_id = ""
    try:
        container_id = _command(
            ("docker", "run", "--detach", "--rm", "--name", container, "-e", f"POSTGRES_PASSWORD={PASSWORD}", "-p", "127.0.0.1::5432", IMAGE),
            capture=True,
        )
        port_line = _command(("docker", "port", container, "5432/tcp"), capture=True)
        port = port_line.rsplit(":", 1)[1]
        source_dsn = f"postgresql://postgres:{PASSWORD}@127.0.0.1:{port}/postgres"
        compatibility_dsn = f"postgresql://postgres:{PASSWORD}@127.0.0.1:{port}/reconforge_compatibility"
        _wait(source_dsn)
        with tempfile.TemporaryDirectory(prefix="reconforge-postgres-upgrade-") as temporary:
            workspace = Path(temporary)
            migrations = PsycopgAlembicMigrationRunner(
                source_dsn=source_dsn,
                compatibility_dsn=compatibility_dsn,
                python_executable=Path(sys.executable).resolve(strict=True),
                alembic_ini=(ROOT / "alembic.ini").resolve(strict=True),
            )
            migrations.upgrade("source", "0052_security_governance")
            native_backup = PostgresNativeBackupAdapter(
                PostgresBackupSettings(
                    source_service="source",
                    maintenance_service="maintenance",
                    restore_database="reconforge_compatibility",
                    tools=_tools(workspace / "tools"),
                    timeout_seconds=1800,
                ),
                runner=DockerPostgresRunner(container),
            )
            adapter = PostgreSQLUpgradeAdapter(
                resource_id="postgres-main",
                backup=native_backup,
                migration_runner=migrations,
                supported_versions={
                    "0.0.52": "0052_security_governance",
                    "0.0.53": "0053_audit_administration_acl",
                },
                recovery_dir=workspace / "recovery",
                backup_key=bytes(range(32)),
            )
            step = UpgradeStep(
                kind="database",
                resource_id="postgres-main",
                from_version="0.0.52",
                to_version="0.0.53",
                target_sha256=postgres_revision_digest("0053_audit_administration_acl"),
                rollback_required=True,
                compatibility_reader="postgres-alembic-restore-v1",
            )
            evidence = adapter.preflight(step)
            receipt = adapter.apply(step, evidence)
            adapter.verify(step, receipt)
            adapter.rollback(step, receipt)
            if migrations.current_revision("source") != "0052_security_governance":
                raise RuntimeError("PostgreSQL source revision was not restored")
            print("postgres_upgrade_drill=passed from=0052 target=0053 rollback=0052 encrypted_backup=verified")
    finally:
        if container_id:
            inspected = _command(("docker", "inspect", "--format", "{{.Id}}", container), capture=True)
            if inspected == container_id:
                _command(("docker", "stop", container))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
