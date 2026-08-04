"""Disposable PostgreSQL synchronous-standby HA/DR and fencing drill."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess  # nosec B404
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

import psycopg
from verify_postgres_upgrade import DockerPostgresRunner, _tools

from reconforge.application.backup_restore import BackupRestoreApplicationService
from reconforge.auth.policy import PolicyEvaluationContext
from reconforge.infrastructure.postgres_backup import PostgresBackupSettings, PostgresNativeBackupAdapter
from reconforge.upgrade.postgres_adapter import PsycopgAlembicMigrationRunner

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "postgres:17.10-alpine"
# Disposable localhost-only credential shared with the fixed Docker tool runner.
PASSWORD = "reconforge-synthetic-upgrade-only"  # nosec B105
KEY = bytes(range(32))
RTO_CEILING_SECONDS = 60.0


def _run(argv: Sequence[str], *, capture: bool = False, allow_failure: bool = False) -> str:
    completed = subprocess.run(  # nosec B603
        tuple(argv), cwd=ROOT, shell=False, check=False, text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=300,
    )
    if completed.returncode != 0 and not allow_failure:
        diagnostic = (completed.stderr or "").replace(PASSWORD, "[redacted]").strip()
        if len(diagnostic) > 4000:
            diagnostic = diagnostic[-4000:]
        suffix = f": {diagnostic}" if diagnostic else ""
        raise RuntimeError(f"HA/DR drill command failed{suffix}")
    return completed.stdout.strip() if capture else ""


def _docker_exec(container: str, command: Sequence[str], *, capture: bool = False) -> str:
    return _run(("docker", "exec", "-e", f"PGPASSWORD={PASSWORD}", container, *command), capture=capture)


def _run_code(argv: Sequence[str], *, timeout_seconds: int) -> int:
    completed = subprocess.run(  # nosec B603
        tuple(argv), cwd=ROOT, shell=False, check=False,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout_seconds,
    )
    return int(completed.returncode)


def _wait_ready(container: str) -> None:
    for _ in range(120):
        result = _run(
            ("docker", "exec", container, "pg_isready", "-U", "postgres", "-d", "postgres"),
            allow_failure=True,
        )
        if result == "":
            check = subprocess.run(  # nosec B603
                ("docker", "exec", container, "pg_isready", "-U", "postgres", "-d", "postgres"),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False, check=False,
            )
            if check.returncode == 0:
                return
        time.sleep(0.5)
    raise RuntimeError("PostgreSQL container did not become ready")


def _port(container: str) -> str:
    return _run(("docker", "port", container, "5432/tcp"), capture=True).rsplit(":", 1)[1]


def _dsn(port: str, database: str = "postgres") -> str:
    return f"postgresql://postgres:{PASSWORD}@127.0.0.1:{port}/{database}"


def _rows_digest(dsn: str) -> tuple[str, int]:
    with psycopg.connect(dsn) as connection:
        rows = connection.execute("SELECT sequence, payload FROM reconforge_dr_sentinel ORDER BY sequence").fetchall()
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest(), len(rows)


def _wait_streaming(primary_dsn: str) -> None:
    for _ in range(120):
        with psycopg.connect(primary_dsn) as connection:
            state = connection.execute("SELECT state FROM pg_stat_replication").fetchone()
        if state is not None and state[0] == "streaming":
            return
        time.sleep(0.5)
    raise RuntimeError("standby did not enter streaming state")


def _context(permission: str) -> PolicyEvaluationContext:
    return PolicyEvaluationContext(user_id="dr-operator", username="dr-operator", user_permissions={permission})


def _safe_remove(kind: str, name: str, drill_id: str) -> None:
    if kind == "container":
        label = _run(("docker", "inspect", "--format", "{{index .Config.Labels \"reconforge.drill\"}}", name), capture=True, allow_failure=True)
        if label == drill_id:
            _run(("docker", "rm", "--force", name), allow_failure=True)
    elif kind == "volume":
        label = _run(("docker", "volume", "inspect", "--format", "{{index .Labels \"reconforge.drill\"}}", name), capture=True, allow_failure=True)
        if label == drill_id:
            _run(("docker", "volume", "rm", "--force", name), allow_failure=True)
    elif kind == "network":
        label = _run(("docker", "network", "inspect", "--format", "{{index .Labels \"reconforge.drill\"}}", name), capture=True, allow_failure=True)
        if label == drill_id:
            _run(("docker", "network", "rm", name), allow_failure=True)


def main() -> int:
    drill_id = "ha-" + os.urandom(6).hex()
    primary = f"reconforge-{drill_id}-primary"
    standby = f"reconforge-{drill_id}-standby"
    control_network = f"reconforge-{drill_id}-control-network"
    replication_network = f"reconforge-{drill_id}-replication-network"
    primary_volume = f"reconforge-{drill_id}-primary-data"
    standby_volume = f"reconforge-{drill_id}-standby-data"
    created: list[tuple[str, str]] = []
    try:
        for network in (control_network, replication_network):
            _run(("docker", "network", "create", "--label", f"reconforge.drill={drill_id}", network))
            created.append(("network", network))
        for volume in (primary_volume, standby_volume):
            _run(("docker", "volume", "create", "--label", f"reconforge.drill={drill_id}", volume))
            created.append(("volume", volume))
        _run(
            (
                "docker", "run", "--detach", "--name", primary, "--label", f"reconforge.drill={drill_id}",
                "--network", control_network, "--publish", "127.0.0.1::5432", "--env", f"POSTGRES_PASSWORD={PASSWORD}",
                "--volume", f"{primary_volume}:/var/lib/postgresql/data", IMAGE,
                "-c", "wal_level=replica", "-c", "max_wal_senders=10", "-c", "max_replication_slots=10",
                "-c", "hot_standby=on",
            )
        )
        created.append(("container", primary))
        _run(("docker", "network", "connect", "--alias", "primary-repl", replication_network, primary))
        _wait_ready(primary)
        primary_port = _port(primary)
        primary_dsn = _dsn(primary_port)
        migrations = PsycopgAlembicMigrationRunner(
            source_dsn=primary_dsn,
            compatibility_dsn=primary_dsn,
            python_executable=Path(sys.executable).resolve(strict=True),
            alembic_ini=(ROOT / "alembic.ini").resolve(strict=True),
        )
        migrations.upgrade("source", "0053_audit_administration_acl")
        _docker_exec(primary, ("psql", "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-c", "CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'reconforge-synthetic-upgrade-only';"))
        _docker_exec(primary, ("sh", "-c", "echo 'host replication replicator all scram-sha-256' >> $PGDATA/pg_hba.conf"))
        _docker_exec(primary, ("psql", "-U", "postgres", "-d", "postgres", "-c", "SELECT pg_reload_conf();"))
        _run(
            (
                "docker", "run", "--rm", "--network", replication_network, "--env", f"PGPASSWORD={PASSWORD}",
                "--volume", f"{standby_volume}:/var/lib/postgresql/data", "--entrypoint", "sh", IMAGE,
                "-c", "rm -rf /var/lib/postgresql/data/* && pg_basebackup -h primary-repl -U replicator -D /var/lib/postgresql/data -Fp -Xs -R -C -S reconforge_dr_slot",
            )
        )
        _run(
            (
                "docker", "run", "--detach", "--name", standby, "--label", f"reconforge.drill={drill_id}",
                "--network", control_network, "--publish", "127.0.0.1::5432", "--env", f"POSTGRES_PASSWORD={PASSWORD}",
                "--volume", f"{standby_volume}:/var/lib/postgresql/data", IMAGE,
            )
        )
        created.append(("container", standby))
        _run(("docker", "network", "connect", "--alias", "standby-repl", replication_network, standby))
        _wait_ready(standby)
        standby_port = _port(standby)
        standby_dsn = _dsn(standby_port)
        _wait_streaming(primary_dsn)
        with psycopg.connect(primary_dsn, autocommit=True) as connection:
            connection.execute("ALTER SYSTEM SET synchronous_standby_names='*'")
            connection.execute("ALTER SYSTEM SET synchronous_commit='remote_apply'")
            connection.execute("SELECT pg_reload_conf()")
        with psycopg.connect(primary_dsn) as connection:
            connection.execute("CREATE TABLE reconforge_dr_sentinel(sequence BIGINT PRIMARY KEY, payload TEXT NOT NULL)")
            connection.execute("INSERT INTO reconforge_dr_sentinel VALUES (1, 'committed-before-failover')")
            connection.commit()
        before_digest, before_count = _rows_digest(primary_dsn)
        for _ in range(60):
            try:
                if _rows_digest(standby_dsn) == (before_digest, before_count):
                    break
            except psycopg.Error:
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError("remote_apply sentinel was not visible on standby")

        with tempfile.TemporaryDirectory(prefix="reconforge-ha-backup-") as temporary:
            workspace = Path(temporary)
            backup = PostgresNativeBackupAdapter(
                PostgresBackupSettings(
                    source_service="source", maintenance_service="maintenance",
                    restore_database="reconforge_restore_drill", tools=_tools(workspace / "tools"), timeout_seconds=1800,
                ),
                runner=DockerPostgresRunner(primary),
            )
            service = BackupRestoreApplicationService(backup)
            artifact = workspace / "ha-dr.rfpgbackup"
            service.create_backup(_context("operations.backup.create"), artifact, key=KEY)
            service.restore_backup(_context("operations.restore.execute"), artifact, key=KEY)
            restore_digest, restore_count = _rows_digest(_dsn(primary_port, "reconforge_restore_drill"))
            if (restore_digest, restore_count) != (before_digest, before_count):
                raise RuntimeError("isolated restore did not reproduce the committed sentinel set")
            backup.drop_restored_database()

        _run(("docker", "network", "disconnect", replication_network, standby))
        partition_write_rejected = _run_code(
            (
                "docker", "exec", "-e", f"PGPASSWORD={PASSWORD}", primary, "sh", "-c",
                "timeout 3 psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \"INSERT INTO reconforge_dr_sentinel VALUES (99, 'unacknowledged-during-partition')\"",
            ),
            timeout_seconds=10,
        ) != 0
        if not partition_write_rejected:
            raise RuntimeError("synchronous partition write unexpectedly acknowledged")

        failover_started = time.perf_counter()
        primary_id = _run(("docker", "inspect", "--format", "{{.Id}}", primary), capture=True)
        _run(("docker", "stop", "--time", "10", primary))
        inspected_id = _run(("docker", "inspect", "--format", "{{.Id}}", primary), capture=True)
        running = _run(("docker", "inspect", "--format", "{{.State.Running}}", primary), capture=True)
        if inspected_id != primary_id or running != "false":
            raise RuntimeError("primary fencing identity/state verification failed")
        _run(("docker", "rm", primary))
        created.remove(("container", primary))
        remaining_primary = _run(
            ("docker", "ps", "--all", "--filter", f"name=^/{primary}$", "--format", "{{.ID}}"),
            capture=True,
        )
        if remaining_primary:
            raise RuntimeError("fenced primary container still exists")
        promoted = _docker_exec(
            standby,
            ("psql", "-U", "postgres", "-d", "postgres", "-At", "-v", "ON_ERROR_STOP=1", "-c", "SELECT pg_promote(true, 60);"),
            capture=True,
        )
        if promoted != "t":
            raise RuntimeError("standby promotion was not acknowledged")
        _run(("docker", "network", "connect", "--alias", "standby-repl", replication_network, standby))
        for _ in range(120):
            try:
                with psycopg.connect(standby_dsn) as connection:
                    recovery_row = connection.execute("SELECT pg_is_in_recovery()").fetchone()
                    if recovery_row is None:
                        raise RuntimeError("promoted standby returned no recovery state")
                    recovery = recovery_row[0]
                    if recovery is False:
                        connection.execute("INSERT INTO reconforge_dr_sentinel VALUES (2, 'committed-after-failover')")
                        connection.commit()
                        break
            except psycopg.Error:
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError("standby promotion did not become writable")
        rto_seconds = time.perf_counter() - failover_started
        after_digest, _after_count = _rows_digest(standby_dsn)
        with psycopg.connect(standby_dsn) as connection:
            sequences = [row[0] for row in connection.execute("SELECT sequence FROM reconforge_dr_sentinel ORDER BY sequence")]
        if sequences != [1, 2] or rto_seconds > RTO_CEILING_SECONDS:
            raise RuntimeError("HA/DR RPO or RTO gate failed")

        rejoined = f"reconforge-{drill_id}-rejoined-primary"
        _docker_exec(
            standby,
            (
                "sh", "-c",
                "printf \"\\nsynchronous_standby_names = ''\\nsynchronous_commit = 'local'\\n\" >> \"$PGDATA/postgresql.conf\" && kill -HUP 1",
            ),
        )
        for _ in range(60):
            bootstrap_settings = _docker_exec(
                standby,
                (
                    "psql", "-U", "postgres", "-d", "postgres", "-At", "-c",
                    "SELECT current_setting('synchronous_standby_names') = '', current_setting('synchronous_commit')",
                ),
                capture=True,
            )
            if bootstrap_settings == "t|local":
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("promoted primary did not enter bounded rejoin bootstrap mode")
        _run(
            (
                "docker", "run", "--rm", "--network", replication_network, "--env", f"PGPASSWORD={PASSWORD}",
                "--volume", f"{primary_volume}:/var/lib/postgresql/data", "--entrypoint", "sh", IMAGE,
                "-c", "rm -rf /var/lib/postgresql/data/* && pg_basebackup -h standby-repl -U replicator -D /var/lib/postgresql/data -Fp -Xs -R -C -S reconforge_failback_slot",
            )
        )
        _run(
            (
                "docker", "run", "--detach", "--name", rejoined, "--label", f"reconforge.drill={drill_id}",
                "--network", control_network, "--publish", "127.0.0.1::5432", "--env", f"POSTGRES_PASSWORD={PASSWORD}",
                "--volume", f"{primary_volume}:/var/lib/postgresql/data", IMAGE,
            )
        )
        created.append(("container", rejoined))
        _run(("docker", "network", "connect", replication_network, rejoined))
        _wait_ready(rejoined)
        rejoined_dsn = _dsn(_port(rejoined))
        _wait_streaming(standby_dsn)
        with psycopg.connect(standby_dsn, autocommit=True) as connection:
            connection.execute("ALTER SYSTEM SET synchronous_standby_names='*'")
            connection.execute("ALTER SYSTEM SET synchronous_commit='remote_apply'")
            connection.execute("SELECT pg_reload_conf()")
        with psycopg.connect(rejoined_dsn) as connection:
            recovery_row = connection.execute("SELECT pg_is_in_recovery()").fetchone()
        if recovery_row is None or recovery_row[0] is not True or _rows_digest(rejoined_dsn) != (after_digest, 2):
            raise RuntimeError("former primary did not rejoin as an exact read-only standby")
        with psycopg.connect(standby_dsn) as connection:
            connection.execute("INSERT INTO reconforge_dr_sentinel VALUES (3, 'committed-before-failback')")
            connection.commit()
        expected_before_failback = _rows_digest(standby_dsn)
        if _rows_digest(rejoined_dsn) != expected_before_failback:
            raise RuntimeError("rejoined standby did not remote-apply the failback sentinel")

        failback_started = time.perf_counter()
        promoted_id = _run(("docker", "inspect", "--format", "{{.Id}}", standby), capture=True)
        _run(("docker", "stop", "--time", "10", standby))
        if _run(("docker", "inspect", "--format", "{{.State.Running}}", standby), capture=True) != "false":
            raise RuntimeError("promoted primary did not enter the fenced stopped state")
        _run(("docker", "rm", standby))
        created.remove(("container", standby))
        if _run(("docker", "ps", "--all", "--filter", f"name=^/{standby}$", "--format", "{{.ID}}"), capture=True):
            raise RuntimeError("former promoted primary still exists before failback")
        failback_promoted = _docker_exec(
            rejoined,
            ("psql", "-U", "postgres", "-d", "postgres", "-At", "-v", "ON_ERROR_STOP=1", "-c", "SELECT pg_promote(true, 60);"),
            capture=True,
        )
        if failback_promoted != "t":
            raise RuntimeError("failback promotion was not acknowledged")
        for _ in range(120):
            try:
                with psycopg.connect(rejoined_dsn) as connection:
                    if connection.execute("SELECT pg_is_in_recovery()").fetchone() == (False,):
                        connection.execute("INSERT INTO reconforge_dr_sentinel VALUES (4, 'committed-after-failback')")
                        connection.commit()
                        break
            except psycopg.Error:
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError("failback target did not become writable")
        failback_rto_seconds = time.perf_counter() - failback_started
        final_digest, final_count = _rows_digest(rejoined_dsn)
        with psycopg.connect(rejoined_dsn) as connection:
            final_sequences = [row[0] for row in connection.execute("SELECT sequence FROM reconforge_dr_sentinel ORDER BY sequence")]
        if final_sequences != [1, 2, 3, 4] or final_count != 4 or failback_rto_seconds > RTO_CEILING_SECONDS:
            raise RuntimeError("failback RPO, integrity, or RTO gate failed")
        print(
            json.dumps(
                {
                    "after_failover_digest": after_digest,
                    "before_failure_digest": before_digest,
                    "fenced_primary_container_id_sha256": hashlib.sha256(primary_id.encode("ascii")).hexdigest(),
                    "failback_fenced_container_id_sha256": hashlib.sha256(promoted_id.encode("ascii")).hexdigest(),
                    "failback_final_digest": final_digest,
                    "failback_rpo_transactions": 0,
                    "failback_rto_seconds": round(failback_rto_seconds, 3),
                    "former_primary_rejoined_read_only": True,
                    "image": IMAGE,
                    "isolated_restore_matches_pre_failure": restore_digest == before_digest,
                    "primary_absent_before_promotion": remaining_primary == "",
                    "restored_rows": restore_count,
                    "rpo_transactions": 0,
                    "rto_ceiling_seconds": RTO_CEILING_SECONDS,
                    "rto_seconds": round(rto_seconds, 3),
                    "network_partition_commit_not_acknowledged": partition_write_rejected,
                    "sentinel_sequences": final_sequences,
                    "standby_remote_apply_matches_pre_failure": before_count == 1,
                    "split_brain_fence": "verified-stopped-and-removed-before-promotion",
                    "topology": "docker-single-host-primary-synchronous-standby-v1",
                },
                sort_keys=True,
            )
        )
    finally:
        for kind, name in reversed(created):
            _safe_remove(kind, name, drill_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
