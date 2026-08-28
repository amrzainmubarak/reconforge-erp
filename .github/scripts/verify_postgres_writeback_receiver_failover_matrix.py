"""Prove write-back receiver replay across synchronous PostgreSQL failover."""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import platform
import secrets
import subprocess  # nosec B404 - shell-free fixed executable boundaries below
import sys
import tempfile
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from psycopg import Error as PsycopgError
from psycopg import connect, sql

from reconforge.connectors.writeback_receiver import (
    SQLiteWritebackReceiverStore,
    WritebackReceiverDisposition,
    WritebackReceiverRequest,
    build_writeback_receiver_response,
)
from reconforge.connectors.writeback_receiver_postgres import (
    SCHEMA_NAME,
    PostgresWritebackReceiverStore,
)

ROOT = Path(__file__).resolve().parents[2]
RECEIVER_SOURCE = ROOT / "reconforge/connectors/writeback_receiver.py"
POSTGRES_RECEIVER_SOURCE = ROOT / "reconforge/connectors/writeback_receiver_postgres.py"
SUPPLY_CHAIN_POLICY_PATH = ROOT / "docs/security/supply-chain-policy.v1.json"

POSTGRES_16_IMAGE = "postgres:16-alpine"
POSTGRES_16_IMAGE_REFERENCE = (
    f"{POSTGRES_16_IMAGE}@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777"
)
POSTGRES_17_IMAGE = "postgres:17.10-alpine"
POSTGRES_17_IMAGE_REFERENCE = (
    f"{POSTGRES_17_IMAGE}@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"
)
PROFILES = (
    {"postgresql": "16.14", "image": POSTGRES_16_IMAGE_REFERENCE, "prefix": "rf-receiver-ha-pg16"},
    {"postgresql": "17.10", "image": POSTGRES_17_IMAGE_REFERENCE, "prefix": "rf-receiver-ha-pg17"},
)
APP_ROLE = "receiver_failover_app"
REPLICATION_ROLE = "receiver_failover_replication"
RTO_CEILING_SECONDS = 60.0


class ReceiverFailoverError(RuntimeError):
    """Raised when the bounded synchronous receiver failover proof fails."""


class _ProcessLike(Protocol):
    @property
    def exitcode(self) -> int | None: ...

    def is_alive(self) -> bool: ...

    def join(self, timeout: float | None = None) -> None: ...

    def terminate(self) -> None: ...


def _progress(stage: str) -> None:
    print(f"receiver_failover_progress={stage}", file=sys.stderr, flush=True)


def _run(
    argv: Sequence[str],
    *,
    capture: bool = False,
    allow_failure: bool = False,
) -> str:
    completed = subprocess.run(  # nosec B603 - shell-free fixed command boundary
        tuple(argv),
        cwd=ROOT,
        shell=False,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=300,
    )
    if completed.returncode != 0 and not allow_failure:
        raise ReceiverFailoverError("disposable PostgreSQL receiver failover command failed")
    return completed.stdout.strip() if capture else ""


def _source_digest(path: Path) -> str:
    canonical = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _base_commit() -> str:
    return _run(("git", "rev-parse", "HEAD"), capture=True)


def _dsn(port: str, *, user: str, password: str) -> str:
    return f"postgresql://{user}:{password}@127.0.0.1:{port}/postgres"


def _port(container: str) -> str:
    return _run(("docker", "port", container, "5432/tcp"), capture=True).rsplit(":", 1)[-1]


def _wait_ready(container: str) -> None:
    for _ in range(120):
        probe = _run(
            (
                "docker",
                "exec",
                container,
                "psql",
                "--username=postgres",
                "--dbname=postgres",
                "--tuples-only",
                "--no-align",
                "--command=SELECT 1",
            ),
            capture=True,
            allow_failure=True,
        )
        if probe == "1":
            return
        time.sleep(0.5)
    raise ReceiverFailoverError("PostgreSQL receiver failover node did not become ready")


def _wait_dsn(dsn: str) -> None:
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        try:
            with connect(dsn, connect_timeout=2) as connection:
                if connection.execute("SELECT 1").fetchone() == (1,):
                    return
        except PsycopgError:
            pass
        time.sleep(0.25)
    raise ReceiverFailoverError("PostgreSQL receiver host connection did not become ready")


def _wait_streaming(primary_dsn: str, *, require_synchronous: bool) -> None:
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        try:
            with connect(primary_dsn, connect_timeout=2) as connection:
                row = connection.execute(
                    "SELECT state, sync_state FROM pg_stat_replication ORDER BY pid LIMIT 1"
                ).fetchone()
            if row is not None and row[0] == "streaming" and (
                not require_synchronous or row[1] == "sync"
            ):
                return
        except PsycopgError:
            pass
        time.sleep(0.5)
    qualifier = "synchronous streaming" if require_synchronous else "streaming"
    raise ReceiverFailoverError(f"PostgreSQL receiver standby did not reach {qualifier}")


def _wait_writable(dsn: str) -> None:
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        try:
            with connect(dsn, connect_timeout=2) as connection:
                row = connection.execute("SELECT pg_is_in_recovery()").fetchone()
            if row == (False,):
                return
        except PsycopgError:
            pass
        time.sleep(0.25)
    raise ReceiverFailoverError("promoted PostgreSQL receiver node did not become writable")


def _request(key: str, *, payload: bytes) -> WritebackReceiverRequest:
    return WritebackReceiverRequest(
        schema_version="writeback-receiver-request-v1",
        receiver_id="synthetic-failover-provider",
        operation="payment.create",
        idempotency_key=key,
        payload_digest=hashlib.sha256(payload).hexdigest(),
    )


def _commit_without_delivering_response(
    dsn: str,
    request_data: dict[str, Any],
    committed: multiprocessing.synchronize.Event,
) -> None:
    request = WritebackReceiverRequest.model_validate(request_data)
    result = PostgresWritebackReceiverStore(dsn).receive(request)
    if result.disposition is not WritebackReceiverDisposition.APPLIED:
        os._exit(91)
    committed.set()
    os._exit(0)


def _attempt_partitioned_receive(dsn: str, request_data: dict[str, Any]) -> None:
    request = WritebackReceiverRequest.model_validate(request_data)
    result = PostgresWritebackReceiverStore(dsn).receive(request)
    os._exit(0 if result.disposition is WritebackReceiverDisposition.APPLIED else 92)


def _wait_sync_rep_commit(admin_dsn: str) -> None:
    for _ in range(80):
        with connect(admin_dsn) as connection:
            row = connection.execute(
                "SELECT pid FROM pg_stat_activity "
                "WHERE usename = %s AND state = 'active' "
                "AND wait_event_type = 'IPC' AND wait_event = 'SyncRep' "
                "AND query = 'COMMIT' ORDER BY pid LIMIT 1",
                (APP_ROLE,),
            ).fetchone()
        if row is not None:
            return
        time.sleep(0.25)
    raise ReceiverFailoverError("partitioned receiver client did not enter SyncRep COMMIT wait")


def _join(process: _ProcessLike, *, label: str) -> None:
    process.join(timeout=40)
    if process.is_alive():
        process.terminate()
        process.join(timeout=10)
        raise ReceiverFailoverError(f"{label} timed out")
    if process.exitcode != 0:
        raise ReceiverFailoverError(f"{label} failed")


def _create_roles_and_receiver(
    admin_dsn: str,
    *,
    app_password: str,
    replication_password: str,
) -> None:
    with connect(admin_dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOINHERIT NOREPLICATION NOBYPASSRLS"
            ).format(sql.Identifier(APP_ROLE), sql.Literal(app_password))
        )
        connection.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOINHERIT REPLICATION NOBYPASSRLS"
            ).format(sql.Identifier(REPLICATION_ROLE), sql.Literal(replication_password))
        )
    PostgresWritebackReceiverStore(admin_dsn).initialize()
    with connect(admin_dsn) as connection:
        connection.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(sql.Identifier(SCHEMA_NAME)))
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE postgres TO {}").format(sql.Identifier(APP_ROLE))
        )
        connection.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(SCHEMA_NAME), sql.Identifier(APP_ROLE)
            )
        )
        connection.execute(
            sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {}, {} TO {}").format(
                sql.Identifier(SCHEMA_NAME, "writeback_receiver_receipts"),
                sql.Identifier(SCHEMA_NAME, "writeback_receiver_effects"),
                sql.Identifier(APP_ROLE),
            )
        )


def _role_flags(admin_dsn: str) -> dict[str, bool]:
    with connect(admin_dsn) as connection:
        row = connection.execute(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
            "FROM pg_roles WHERE rolname = %s",
            (APP_ROLE,),
        ).fetchone()
    if row is None:
        raise ReceiverFailoverError("receiver failover application role is missing")
    return {
        "superuser": bool(row[0]),
        "create_database": bool(row[1]),
        "create_role": bool(row[2]),
        "replication": bool(row[3]),
        "bypass_rls": bool(row[4]),
    }


def _set_replication_policy(admin_dsn: str, *, synchronous: bool) -> None:
    names = "*" if synchronous else ""
    commit = "remote_apply" if synchronous else "local"
    with connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("ALTER SYSTEM SET synchronous_standby_names = {}").format(sql.Literal(names)))
        connection.execute(sql.SQL("ALTER SYSTEM SET synchronous_commit = {}").format(sql.Literal(commit)))
        connection.execute("SELECT pg_reload_conf()")
    for _ in range(60):
        with connect(admin_dsn) as connection:
            row = connection.execute(
                "SELECT current_setting('synchronous_standby_names'), current_setting('synchronous_commit')"
            ).fetchone()
        if row == (names, commit):
            return
        time.sleep(0.25)
    raise ReceiverFailoverError("receiver failover replication policy did not converge")


def _append_replication_hba(container: str) -> None:
    _run(
        (
            "docker",
            "exec",
            container,
            "sh",
            "-ceu",
            "printf '%s\\n' 'host replication receiver_failover_replication all scram-sha-256' "
            ">> \"$PGDATA/pg_hba.conf\"",
        )
    )
    _run(
        (
            "docker",
            "exec",
            container,
            "psql",
            "--username=postgres",
            "--dbname=postgres",
            "--command=SELECT pg_reload_conf()",
        )
    )


def _basebackup(
    *,
    image: str,
    network: str,
    source_alias: str,
    volume: str,
    replication_password: str,
    slot: str,
) -> None:
    _run(
        (
            "docker",
            "run",
            "--rm",
            "--network",
            network,
            "--env",
            f"PGPASSWORD={replication_password}",
            "--volume",
            f"{volume}:/var/lib/postgresql/data",
            "--entrypoint",
            "sh",
            image,
            "-ceu",
            "rm -rf /var/lib/postgresql/data/*; "
            f"pg_basebackup --host={source_alias} --username={REPLICATION_ROLE} "
            "--pgdata=/var/lib/postgresql/data --format=plain --wal-method=stream "
            f"--write-recovery-conf --create-slot --slot={slot}",
        )
    )


def _safe_remove(kind: str, name: str, drill_id: str) -> None:
    if kind == "container":
        label = _run(
            ("docker", "inspect", "--format", '{{index .Config.Labels "reconforge.receiver_failover"}}', name),
            capture=True,
            allow_failure=True,
        )
        if label == drill_id:
            _run(("docker", "rm", "--force", name), allow_failure=True)
    elif kind == "volume":
        label = _run(
            ("docker", "volume", "inspect", "--format", '{{index .Labels "reconforge.receiver_failover"}}', name),
            capture=True,
            allow_failure=True,
        )
        if label == drill_id:
            _run(("docker", "volume", "rm", "--force", name), allow_failure=True)
    elif kind == "network":
        label = _run(
            ("docker", "network", "inspect", "--format", '{{index .Labels "reconforge.receiver_failover"}}', name),
            capture=True,
            allow_failure=True,
        )
        if label == drill_id:
            _run(("docker", "network", "rm", name), allow_failure=True)


def _assert_cleanup(drill_id: str) -> None:
    queries = (
        ("docker", "ps", "--all", "--filter", f"label=reconforge.receiver_failover={drill_id}", "--format", "{{.ID}}"),
        ("docker", "volume", "ls", "--filter", f"label=reconforge.receiver_failover={drill_id}", "--format", "{{.Name}}"),
        ("docker", "network", "ls", "--filter", f"label=reconforge.receiver_failover={drill_id}", "--format", "{{.Name}}"),
    )
    if any(_run(query, capture=True) for query in queries):
        raise ReceiverFailoverError("receiver failover cleanup left labelled Docker resources")


def run_observation(*, image: str, expected_postgresql: str, prefix: str) -> dict[str, Any]:
    drill_id = prefix + "-" + secrets.token_hex(6)
    label = f"reconforge.receiver_failover={drill_id}"
    primary = drill_id + "-primary"
    standby = drill_id + "-standby"
    rejoined = drill_id + "-rejoined"
    control_network = drill_id + "-control"
    replication_network = drill_id + "-replication"
    primary_volume = drill_id + "-primary-data"
    standby_volume = drill_id + "-standby-data"
    admin_password = secrets.token_urlsafe(24)
    app_password = secrets.token_urlsafe(24)
    replication_password = secrets.token_urlsafe(24)
    created: list[tuple[str, str]] = []
    observation: dict[str, Any] | None = None
    try:
        _progress(prefix + ":topology_start")
        for network in (control_network, replication_network):
            _run(("docker", "network", "create", "--label", label, network))
            created.append(("network", network))
        for volume in (primary_volume, standby_volume):
            _run(("docker", "volume", "create", "--label", label, volume))
            created.append(("volume", volume))
        _run(
            (
                "docker",
                "run",
                "--detach",
                "--name",
                primary,
                "--label",
                label,
                "--network",
                control_network,
                "--publish",
                "127.0.0.1::5432",
                "--env",
                f"POSTGRES_PASSWORD={admin_password}",
                "--volume",
                f"{primary_volume}:/var/lib/postgresql/data",
                image,
                "-c",
                "wal_level=replica",
                "-c",
                "max_wal_senders=10",
                "-c",
                "max_replication_slots=10",
                "-c",
                "hot_standby=on",
            )
        )
        created.append(("container", primary))
        _run(("docker", "network", "connect", "--alias", "primary-repl", replication_network, primary))
        _wait_ready(primary)
        primary_port = _port(primary)
        primary_admin_dsn = _dsn(primary_port, user="postgres", password=admin_password)
        primary_app_dsn = _dsn(primary_port, user=APP_ROLE, password=app_password)
        _wait_dsn(primary_admin_dsn)
        with connect(primary_admin_dsn) as connection:
            version_row = connection.execute("SHOW server_version").fetchone()
        postgresql = "" if version_row is None else str(version_row[0])
        if postgresql != expected_postgresql:
            raise ReceiverFailoverError("PostgreSQL receiver failover runtime version drifted")
        _progress(prefix + ":primary_ready")

        _create_roles_and_receiver(
            primary_admin_dsn,
            app_password=app_password,
            replication_password=replication_password,
        )
        _append_replication_hba(primary)
        _basebackup(
            image=image,
            network=replication_network,
            source_alias="primary-repl",
            volume=standby_volume,
            replication_password=replication_password,
            slot="receiver_failover_initial_slot",
        )
        _run(
            (
                "docker",
                "run",
                "--detach",
                "--name",
                standby,
                "--label",
                label,
                "--network",
                control_network,
                "--publish",
                "127.0.0.1::5432",
                "--env",
                f"POSTGRES_PASSWORD={admin_password}",
                "--volume",
                f"{standby_volume}:/var/lib/postgresql/data",
                image,
            )
        )
        created.append(("container", standby))
        _run(("docker", "network", "connect", "--alias", "standby-repl", replication_network, standby))
        _wait_ready(standby)
        standby_port = _port(standby)
        standby_admin_dsn = _dsn(standby_port, user="postgres", password=admin_password)
        standby_app_dsn = _dsn(standby_port, user=APP_ROLE, password=app_password)
        _wait_dsn(standby_admin_dsn)
        _wait_streaming(primary_admin_dsn, require_synchronous=False)
        _set_replication_policy(primary_admin_dsn, synchronous=True)
        _wait_streaming(primary_admin_dsn, require_synchronous=True)
        _progress(prefix + ":initial_remote_apply_ready")

        flags = _role_flags(primary_admin_dsn)
        if any(flags.values()):
            raise ReceiverFailoverError("receiver failover application role is privileged")
        acknowledged = _request(
            "receiver-ha-acknowledged-1",
            payload=b'{"reference":"acknowledged-before-failover"}',
        )
        partitioned = _request(
            "receiver-ha-partitioned-1",
            payload=b'{"reference":"unacknowledged-during-partition"}',
        )
        expected_acknowledged_response = build_writeback_receiver_response(
            acknowledged.idempotency_key,
            "rf-receiver-" + acknowledged.request_digest[:24],
        )
        context = multiprocessing.get_context("spawn")
        committed = context.Event()
        child = context.Process(
            target=_commit_without_delivering_response,
            args=(primary_app_dsn, acknowledged.model_dump(mode="json"), committed),
        )
        child.start()
        if not committed.wait(timeout=40):
            if child.is_alive():
                child.terminate()
                child.join(timeout=10)
            raise ReceiverFailoverError("acknowledged receiver commit was not observed")
        _join(child, label="receiver response-loss child")

        standby_before = PostgresWritebackReceiverStore(standby_app_dsn)
        before_counts = standby_before.counts()
        before_history = standby_before.canonical_history_digest()
        if before_counts.receipts != 1 or before_counts.effects != 1:
            raise ReceiverFailoverError("remote_apply did not preserve acknowledged receiver effect")
        _progress(prefix + ":acknowledged_effect_remote_applied")

        _run(("docker", "network", "disconnect", replication_network, standby))
        partition_child = context.Process(
            target=_attempt_partitioned_receive,
            args=(primary_app_dsn, partitioned.model_dump(mode="json")),
        )
        partition_child.start()
        _wait_sync_rep_commit(primary_admin_dsn)
        partition_child.terminate()
        partition_child.join(timeout=10)
        if partition_child.is_alive():
            partition_child.terminate()
            partition_child.join(timeout=10)
            raise ReceiverFailoverError("partitioned receiver client did not terminate")
        if partition_child.exitcode in (None, 0):
            raise ReceiverFailoverError("partitioned receiver client unexpectedly received a result")
        partition_outcome = "client_terminated_while_commit_waited_sync_rep"
        _progress(prefix + ":partition_uncertainty_observed")

        failover_started = time.perf_counter()
        primary_id = _run(("docker", "inspect", "--format", "{{.Id}}", primary), capture=True)
        _run(("docker", "stop", "--time", "5", primary))
        if _run(("docker", "inspect", "--format", "{{.Id}}", primary), capture=True) != primary_id:
            raise ReceiverFailoverError("receiver failover primary identity drifted during fencing")
        if _run(("docker", "inspect", "--format", "{{.State.Running}}", primary), capture=True) != "false":
            raise ReceiverFailoverError("receiver failover primary was not stopped")
        _run(("docker", "rm", primary))
        created.remove(("container", primary))
        if _run(
            ("docker", "ps", "--all", "--filter", f"name=^/{primary}$", "--format", "{{.ID}}"),
            capture=True,
        ):
            raise ReceiverFailoverError("fenced receiver primary still exists")

        promoted = _run(
            (
                "docker",
                "exec",
                standby,
                "psql",
                "--username=postgres",
                "--dbname=postgres",
                "--tuples-only",
                "--no-align",
                "--command=SELECT pg_promote(true, 60)",
            ),
            capture=True,
        )
        if promoted != "t":
            raise ReceiverFailoverError("receiver standby promotion was not acknowledged")
        _wait_writable(standby_admin_dsn)
        _run(
            (
                "docker",
                "network",
                "connect",
                "--alias",
                "standby-repl",
                replication_network,
                standby,
            )
        )
        promoted_store = PostgresWritebackReceiverStore(standby_app_dsn)
        replay_after_failover = promoted_store.receive(acknowledged)
        after_promotion_counts = promoted_store.counts()
        if (
            replay_after_failover.disposition is not WritebackReceiverDisposition.REPLAYED
            or replay_after_failover.response != expected_acknowledged_response
            or after_promotion_counts != before_counts
        ):
            raise ReceiverFailoverError("acknowledged receiver effect did not replay exactly after failover")
        if promoted_store.canonical_history_digest() != before_history:
            raise ReceiverFailoverError("receiver history changed during failover replay")
        failover_rto_seconds = time.perf_counter() - failover_started
        if failover_rto_seconds > RTO_CEILING_SECONDS:
            raise ReceiverFailoverError("receiver failover exceeded the bounded RTO ceiling")
        _progress(prefix + ":promotion_replay_verified")

        _set_replication_policy(standby_admin_dsn, synchronous=False)
        _basebackup(
            image=image,
            network=replication_network,
            source_alias="standby-repl",
            volume=primary_volume,
            replication_password=replication_password,
            slot="receiver_failover_rejoin_slot",
        )
        _run(
            (
                "docker",
                "run",
                "--detach",
                "--name",
                rejoined,
                "--label",
                label,
                "--network",
                control_network,
                "--publish",
                "127.0.0.1::5432",
                "--env",
                f"POSTGRES_PASSWORD={admin_password}",
                "--volume",
                f"{primary_volume}:/var/lib/postgresql/data",
                image,
            )
        )
        created.append(("container", rejoined))
        _run(("docker", "network", "connect", replication_network, rejoined))
        _wait_ready(rejoined)
        rejoined_port = _port(rejoined)
        rejoined_app_dsn = _dsn(rejoined_port, user=APP_ROLE, password=app_password)
        _wait_dsn(_dsn(rejoined_port, user="postgres", password=admin_password))
        _wait_streaming(standby_admin_dsn, require_synchronous=False)
        _set_replication_policy(standby_admin_dsn, synchronous=True)
        _wait_streaming(standby_admin_dsn, require_synchronous=True)
        _progress(prefix + ":rejoin_remote_apply_ready")

        rejoined_before = PostgresWritebackReceiverStore(rejoined_app_dsn)
        if (
            rejoined_before.counts() != before_counts
            or rejoined_before.canonical_history_digest() != before_history
        ):
            raise ReceiverFailoverError("rejoined receiver standby did not preserve failover history")
        partition_retry = promoted_store.receive(partitioned)
        if partition_retry.disposition is not WritebackReceiverDisposition.APPLIED:
            raise ReceiverFailoverError("uncertain partition request did not apply once after redundancy")
        promoted_counts = promoted_store.counts()
        promoted_history = promoted_store.canonical_history_digest()
        rejoined_counts = rejoined_before.counts()
        rejoined_history = rejoined_before.canonical_history_digest()
        if (
            promoted_counts.receipts != 2
            or promoted_counts.effects != 2
            or rejoined_counts != promoted_counts
            or rejoined_history != promoted_history
        ):
            raise ReceiverFailoverError("receiver history did not remote-apply after redundancy restoration")
        _progress(prefix + ":partition_retry_remote_applied")

        _progress(prefix + ":promoted_primary_restart_start")
        _run(("docker", "restart", "--time", "5", standby))
        _progress(prefix + ":promoted_primary_restart_command_complete")
        _wait_ready(standby)
        _progress(prefix + ":promoted_primary_restart_internal_ready")
        restarted_port = _port(standby)
        host_port_changed = restarted_port != standby_port
        standby_admin_dsn = _dsn(restarted_port, user="postgres", password=admin_password)
        standby_app_dsn = _dsn(restarted_port, user=APP_ROLE, password=app_password)
        _wait_dsn(standby_admin_dsn)
        _progress(prefix + ":promoted_primary_restart_dsn_ready")
        _wait_streaming(standby_admin_dsn, require_synchronous=True)
        _progress(prefix + ":promoted_primary_restart_ready")
        restarted_store = PostgresWritebackReceiverStore(standby_app_dsn)
        restart_before = restarted_store.counts()
        acknowledged_restart_replay = restarted_store.receive(acknowledged)
        partition_restart_replay = restarted_store.receive(partitioned)
        restart_after = restarted_store.counts()
        restart_history = restarted_store.canonical_history_digest()
        if (
            acknowledged_restart_replay.disposition is not WritebackReceiverDisposition.REPLAYED
            or partition_restart_replay.disposition is not WritebackReceiverDisposition.REPLAYED
            or restart_before != restart_after
            or restart_after != promoted_counts
            or restart_history != promoted_history
        ):
            raise ReceiverFailoverError("receiver replay changed effects after promoted-primary restart")
        _progress(prefix + ":restart_replays_verified")

        checks = {
            "remote_apply_synchronous_before_failure": True,
            "acknowledged_commit_returned_in_child": child.exitcode == 0,
            "response_not_delivered_to_caller": True,
            "acknowledged_effect_visible_on_standby": before_counts.receipts == before_counts.effects == 1,
            "partitioned_commit_became_uncertain": (
                partition_outcome == "client_terminated_while_commit_waited_sync_rep"
            ),
            "sync_rep_commit_wait_observed": True,
            "primary_identity_fenced": True,
            "primary_absent_before_promotion": True,
            "standby_promoted_writable": promoted == "t",
            "acknowledged_effect_replayed_after_failover": replay_after_failover.disposition.value == "replayed",
            "failover_replay_created_no_effect": after_promotion_counts == before_counts,
            "writes_paused_until_redundancy_restored": True,
            "former_primary_reseeded_read_only": True,
            "remote_apply_synchronous_after_rejoin": True,
            "partitioned_request_applied_once_after_rejoin": partition_retry.disposition.value == "applied",
            "post_rejoin_history_equal": rejoined_history == promoted_history,
            "promoted_primary_restart_completed": True,
            "restart_endpoint_rediscovered": bool(restarted_port),
            "restart_replays_created_no_effect": restart_before == restart_after,
            "restart_history_equal": restart_history == promoted_history,
            "non_privileged_application_role": not any(flags.values()),
            "rto_within_local_ceiling": failover_rto_seconds <= RTO_CEILING_SECONDS,
        }
        if not all(checks.values()):
            raise ReceiverFailoverError("receiver failover observation contains a failed check")
        observation = {
            "runtime": {
                "docker_server": _run(("docker", "version", "--format", "{{.Server.Version}}"), capture=True),
                "image": image,
                "postgresql": postgresql,
                "python": platform.python_version(),
                "multiprocessing_start_method": context.get_start_method(),
                "application_role": flags,
                "node_count": 2,
                "failure_domains": 1,
            },
            "cases": {
                "acknowledged_response_loss": {
                    "child_exit_code": child.exitcode,
                    "retry_disposition": replay_after_failover.disposition.value,
                    "request_digest": acknowledged.request_digest,
                    "response_digest": replay_after_failover.response.response_digest,
                },
                "partition_uncertainty": {
                    "primary_outcome": partition_outcome,
                    "client_exit_code": partition_child.exitcode,
                    "sync_rep_wait_observed": True,
                    "retry_disposition": partition_retry.disposition.value,
                    "request_digest": partitioned.request_digest,
                    "response_digest": partition_retry.response.response_digest,
                },
                "promoted_primary_restart": {
                    "host_port_changed": host_port_changed,
                    "endpoint_rediscovered": True,
                    "acknowledged_retry_disposition": acknowledged_restart_replay.disposition.value,
                    "partition_retry_disposition": partition_restart_replay.disposition.value,
                    "receipts_before": restart_before.receipts,
                    "receipts_after": restart_after.receipts,
                    "effects_before": restart_before.effects,
                    "effects_after": restart_after.effects,
                },
            },
            "history": {
                "acknowledged_receipts_before_failover": before_counts.receipts,
                "acknowledged_effects_before_failover": before_counts.effects,
                "before_failover_sha256": before_history,
                "final_receipts": promoted_counts.receipts,
                "final_effects": promoted_counts.effects,
                "final_sha256": promoted_history,
                "rejoined_receipts": rejoined_counts.receipts,
                "rejoined_effects": rejoined_counts.effects,
                "rejoined_sha256": rejoined_history,
                "after_restart_sha256": restart_history,
            },
            "recovery": {
                "fencing": "verified-stopped-and-removed-before-promotion",
                "replication_mode": "physical-streaming-synchronous-remote-apply",
                "writes_during_rejoin": "controller-paused",
                "failover_rto_seconds": round(failover_rto_seconds, 3),
                "rto_ceiling_seconds": RTO_CEILING_SECONDS,
                "acknowledged_effect_rpo": 0,
            },
            "checks": checks,
        }
        _progress(prefix + ":observation_complete")
    finally:
        _progress(prefix + ":cleanup_start")
        for kind, name in reversed(created):
            _safe_remove(kind, name, drill_id)
    _assert_cleanup(drill_id)
    _progress(prefix + ":cleanup_complete")
    if observation is None:
        raise ReceiverFailoverError("receiver failover observation produced no evidence")
    observation["checks"]["cleanup_complete"] = True
    return observation


def _sqlite_reference() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="reconforge-receiver-ha-sqlite-") as temporary:
        store = SQLiteWritebackReceiverStore(Path(temporary) / "receiver.sqlite3")
        store.initialize()
        acknowledged = _request(
            "receiver-ha-acknowledged-1",
            payload=b'{"reference":"acknowledged-before-failover"}',
        )
        partitioned = _request(
            "receiver-ha-partitioned-1",
            payload=b'{"reference":"unacknowledged-during-partition"}',
        )
        store.receive(acknowledged)
        store.receive(partitioned)
        counts = store.counts()
        return {
            "receipts": counts.receipts,
            "effects": counts.effects,
            "canonical_history_sha256": store.canonical_history_digest(),
        }


def run_matrix(output: Path) -> dict[str, Any]:
    started = time.perf_counter()
    reference = _sqlite_reference()
    runs = [
        run_observation(
            image=str(profile["image"]),
            expected_postgresql=str(profile["postgresql"]),
            prefix=str(profile["prefix"]),
        )
        for profile in PROFILES
    ]
    histories = {str(run["history"]["final_sha256"]) for run in runs}
    histories.add(str(reference["canonical_history_sha256"]))
    if len(histories) != 1:
        raise ReceiverFailoverError("SQLite/PostgreSQL failover receiver history parity failed")
    if any(not all(bool(value) for value in run["checks"].values()) for run in runs):
        raise ReceiverFailoverError("receiver failover matrix contains a failed check")
    report: dict[str, Any] = {
        "schema_version": "postgres-writeback-receiver-failover-matrix-v1",
        "executed_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "profile": "single-host-synchronous-receiver-failover-matrix",
        "subject": {
            "base_commit": _base_commit(),
            "receiver_source_sha256": _source_digest(RECEIVER_SOURCE),
            "postgres_receiver_source_sha256": _source_digest(POSTGRES_RECEIVER_SOURCE),
            "matrix_runner_source_sha256": _source_digest(Path(__file__)),
            "supply_chain_policy_sha256": _source_digest(SUPPLY_CHAIN_POLICY_PATH),
        },
        "sqlite_reference": reference,
        "runs": runs,
        "parity": {
            "backends": ["sqlite", "postgresql-16.14-failover", "postgresql-17.10-failover"],
            "canonical_history_sha256": histories.pop(),
            "all_checks_passed": True,
            "all_cleanup_complete": True,
        },
        "limitations": [
            "single_docker_desktop_host_and_one_failure_domain",
            "two_nodes_per_postgresql_version",
            "manual_fencing_promotion_and_rejoin_controller",
            "no_quorum_witness_or_automatic_failover",
            "synthetic_digest_only_effects_and_credentials",
            "no_cross_host_zone_region_or_network_consensus",
            "no_live_provider_accounting_settlement_or_production_claim",
        ],
    }
    report["report_digest"] = _canonical_digest(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    report = run_matrix(arguments.output.resolve(strict=False))
    print(
        "postgres_writeback_receiver_failover_matrix=passed "
        f"report_digest={report['report_digest']} "
        f"history_digest={report['parity']['canonical_history_sha256']}"
    )
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
