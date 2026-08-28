"""Prove PostgreSQL receiver idempotency parity on the declared version matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import platform
import secrets
import subprocess  # nosec B404 - fixed executable/argument vectors below
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from psycopg import Error as PsycopgError
from psycopg import connect, sql

from reconforge.connectors.writeback_receiver import (
    WritebackReceiverDisposition,
    WritebackReceiverError,
    WritebackReceiverRequest,
)
from reconforge.connectors.writeback_receiver_postgres import (
    EFFECTS_TABLE,
    RECEIPTS_TABLE,
    SCHEMA_NAME,
    PostgresWritebackReceiverStore,
)

ROOT = Path(__file__).resolve().parents[2]
RECEIVER_SOURCE = ROOT / "reconforge/connectors/writeback_receiver.py"
POSTGRES_RECEIVER_SOURCE = ROOT / "reconforge/connectors/writeback_receiver_postgres.py"
SQLITE_REPORT_PATH = ROOT / "docs/execution/WRITEBACK_RECEIVER_IDEMPOTENCY_DRILL_2026-08-22.json"
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
    {"postgresql": "16.14", "image": POSTGRES_16_IMAGE_REFERENCE, "prefix": "rf-receiver-pg16"},
    {"postgresql": "17.10", "image": POSTGRES_17_IMAGE_REFERENCE, "prefix": "rf-receiver-pg17"},
)
SOURCE_DATABASE = "receiver_source"
RESTORED_DATABASE = "receiver_restored"
APP_ROLE = "receiver_app"


class ReceiverMatrixError(RuntimeError):
    """Raised when the PostgreSQL receiver matrix is not proven."""


class _ProcessLike(Protocol):
    @property
    def exitcode(self) -> int | None: ...

    def is_alive(self) -> bool: ...

    def join(self, timeout: float | None = None) -> None: ...

    def terminate(self) -> None: ...


def _run(argv: Sequence[str], *, capture: bool = False, expected_exit: int = 0) -> str:
    completed = subprocess.run(  # nosec B603 - shell-free fixed command boundary
        tuple(argv),
        cwd=ROOT,
        shell=False,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
        timeout=300,
    )
    if completed.returncode != expected_exit:
        raise ReceiverMatrixError("disposable PostgreSQL receiver command failed")
    return completed.stdout.strip() if capture else ""


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _source_digest(path: Path) -> str:
    canonical = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _base_commit() -> str:
    return _run(("git", "rev-parse", "HEAD"), capture=True)


def _dsn(port: str, database: str, *, user: str, password: str) -> str:
    return f"postgresql://{user}:{password}@127.0.0.1:{port}/{database}"


def _wait_for_postgres(dsn: str) -> None:
    for _ in range(60):
        try:
            with connect(dsn) as connection:
                connection.execute("SELECT 1")
            return
        except PsycopgError:
            time.sleep(0.5)
    raise ReceiverMatrixError("disposable PostgreSQL receiver did not become ready")


def _request(key: str, *, payload: bytes) -> WritebackReceiverRequest:
    return WritebackReceiverRequest(
        schema_version="writeback-receiver-request-v1",
        receiver_id="synthetic-provider",
        operation="payment.create",
        idempotency_key=key,
        payload_digest=hashlib.sha256(payload).hexdigest(),
    )


def _receive_worker(
    dsn: str,
    request_data: dict[str, Any],
    start: multiprocessing.synchronize.Event,
    results: multiprocessing.queues.Queue,
) -> None:
    start.wait(timeout=20)
    request = WritebackReceiverRequest.model_validate(request_data)
    result = PostgresWritebackReceiverStore(dsn).receive(request)
    results.put((result.disposition.value, result.response.response_digest))


def _crash_after_commit(dsn: str, request_data: dict[str, Any]) -> None:
    request = WritebackReceiverRequest.model_validate(request_data)
    result = PostgresWritebackReceiverStore(dsn).receive(request)
    if result.disposition is not WritebackReceiverDisposition.APPLIED:
        os._exit(91)
    os._exit(0)


def _join(process: _ProcessLike, *, label: str) -> None:
    process.join(timeout=40)
    if process.is_alive():
        process.terminate()
        process.join(timeout=10)
        raise ReceiverMatrixError(f"{label} timed out")
    if process.exitcode != 0:
        raise ReceiverMatrixError(f"{label} failed with exit code {process.exitcode}")


def _create_database_and_role(admin_dsn: str, *, app_password: str) -> None:
    with connect(admin_dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOINHERIT NOREPLICATION NOBYPASSRLS"
            ).format(sql.Identifier(APP_ROLE), sql.Literal(app_password))
        )
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(SOURCE_DATABASE)))
        connection.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(SOURCE_DATABASE)))
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(SOURCE_DATABASE), sql.Identifier(APP_ROLE)
            )
        )


def _grant_application_boundary(source_admin_dsn: str) -> None:
    with connect(source_admin_dsn) as connection:
        connection.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(sql.Identifier(SCHEMA_NAME)))
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


def _immutability_checks(app_dsn: str) -> tuple[bool, bool, bool]:
    update_refused = False
    delete_refused = False
    malformed_insert_refused = False
    with connect(app_dsn) as connection:
        try:
            connection.execute(f"UPDATE {RECEIPTS_TABLE} SET operation = 'changed'")  # nosec B608 - fixed table
        except PsycopgError as exc:
            update_refused = "writeback_receiver_receipt_immutable" in str(exc)
        connection.rollback()
        try:
            connection.execute(f"DELETE FROM {EFFECTS_TABLE}")  # nosec B608 - fixed table
        except PsycopgError as exc:
            delete_refused = "writeback_receiver_effect_immutable" in str(exc)
        connection.rollback()
        try:
            connection.execute(
                f"""
                INSERT INTO {RECEIPTS_TABLE} (
                    receiver_id, idempotency_key, operation, payload_digest,
                    request_digest, provider_reference, response_digest, committed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,  # nosec B608 - fixed table
                (
                    "synthetic-provider",
                    "direct-malformed",
                    "payment.create",
                    "a" * 63,
                    "b" * 64,
                    "rf-receiver-direct-malformed",
                    "c" * 64,
                    datetime.now(UTC),
                ),
            )
        except PsycopgError:
            malformed_insert_refused = True
        connection.rollback()
    return update_refused, delete_refused, malformed_insert_refused


def _role_flags(admin_dsn: str) -> dict[str, bool]:
    with connect(admin_dsn) as connection:
        row = connection.execute(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s",
            (APP_ROLE,),
        ).fetchone()
    if row is None:
        raise ReceiverMatrixError("receiver application role is missing")
    return {
        "superuser": bool(row[0]),
        "create_database": bool(row[1]),
        "create_role": bool(row[2]),
        "replication": bool(row[3]),
        "bypass_rls": bool(row[4]),
    }


def _native_backup_restore(
    *,
    container: str,
    admin_dsn: str,
    port: str,
    app_password: str,
) -> tuple[str, str]:
    dump_path = f"/tmp/writeback-receiver-{secrets.token_hex(12)}.dump"  # nosec B108 - disposable container
    _run(
        (
            "docker",
            "exec",
            container,
            "pg_dump",
            "--username=postgres",
            "--format=custom",
            f"--file={dump_path}",
            SOURCE_DATABASE,
        )
    )
    _run(("docker", "exec", container, "pg_restore", "--list", dump_path))
    dump_sha256 = _run(
        ("docker", "exec", container, "sha256sum", dump_path), capture=True
    ).split()[0]
    with connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(RESTORED_DATABASE)))
        connection.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(RESTORED_DATABASE)))
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(RESTORED_DATABASE), sql.Identifier(APP_ROLE)
            )
        )
    _run(
        (
            "docker",
            "exec",
            container,
            "pg_restore",
            "--username=postgres",
            f"--dbname={RESTORED_DATABASE}",
            dump_path,
        )
    )
    restored_dsn = _dsn(port, RESTORED_DATABASE, user=APP_ROLE, password=app_password)
    return dump_sha256, restored_dsn


def run_observation(*, image: str, expected_postgresql: str, prefix: str) -> dict[str, Any]:
    admin_password = secrets.token_urlsafe(24)
    app_password = secrets.token_urlsafe(24)
    container_name = prefix + "-" + secrets.token_hex(6)
    container_id = ""
    observation: dict[str, Any] | None = None
    cleanup_complete = False
    try:
        container_id = _run(
            (
                "docker",
                "run",
                "--rm",
                "--detach",
                "--name",
                container_name,
                "--env",
                f"POSTGRES_PASSWORD={admin_password}",
                "--publish",
                "127.0.0.1::5432",
                image,
            ),
            capture=True,
        )
        port_output = _run(("docker", "port", container_id, "5432/tcp"), capture=True)
        port = port_output.rsplit(":", 1)[-1]
        admin_dsn = _dsn(port, "postgres", user="postgres", password=admin_password)
        _wait_for_postgres(admin_dsn)
        with connect(admin_dsn) as connection:
            version_row = connection.execute("SHOW server_version").fetchone()
        postgresql = "" if version_row is None else str(version_row[0])
        if postgresql != expected_postgresql:
            raise ReceiverMatrixError("PostgreSQL receiver runtime version drifted")

        _create_database_and_role(admin_dsn, app_password=app_password)
        source_admin_dsn = _dsn(port, SOURCE_DATABASE, user="postgres", password=admin_password)
        PostgresWritebackReceiverStore(source_admin_dsn).initialize()
        _grant_application_boundary(source_admin_dsn)
        app_dsn = _dsn(port, SOURCE_DATABASE, user=APP_ROLE, password=app_password)
        store = PostgresWritebackReceiverStore(app_dsn)

        sequential = _request("receiver-sequential-1", payload=b'{"reference":"sequential"}')
        first = store.receive(sequential)
        replay = store.receive(sequential)
        if first.disposition is not WritebackReceiverDisposition.APPLIED or replay.response != first.response:
            raise ReceiverMatrixError("PostgreSQL sequential receiver replay failed")

        conflict_refused = False
        try:
            store.receive(_request("receiver-sequential-1", payload=b'{"reference":"retargeted"}'))
        except WritebackReceiverError as exc:
            conflict_refused = str(exc) == "writeback_receiver_idempotency_conflict"
        if not conflict_refused:
            raise ReceiverMatrixError("PostgreSQL receiver key retargeting was not refused")

        context = multiprocessing.get_context("spawn")
        concurrent = _request("receiver-concurrent-1", payload=b'{"reference":"concurrent"}')
        start = context.Event()
        results = context.Queue()
        processes = [
            context.Process(
                target=_receive_worker,
                args=(app_dsn, concurrent.model_dump(mode="json"), start, results),
            )
            for _ in range(8)
        ]
        try:
            for process in processes:
                process.start()
            start.set()
            concurrent_results = [results.get(timeout=40) for _ in processes]
            for index, process in enumerate(processes):
                _join(process, label=f"PostgreSQL receiver process {index}")
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=10)
            results.close()
            results.join_thread()
        dispositions = [item[0] for item in concurrent_results]
        response_digests = {item[1] for item in concurrent_results}
        if dispositions.count("applied") != 1 or dispositions.count("replayed") != 7 or len(response_digests) != 1:
            raise ReceiverMatrixError("PostgreSQL receiver concurrency did not converge")

        crash = _request("receiver-crash-1", payload=b'{"reference":"crash"}')
        crash_process = context.Process(
            target=_crash_after_commit,
            args=(app_dsn, crash.model_dump(mode="json")),
        )
        crash_process.start()
        _join(crash_process, label="PostgreSQL receiver crash-after-commit")
        crash_replay = store.receive(crash)

        update_refused, delete_refused, malformed_insert_refused = _immutability_checks(app_dsn)
        counts = store.counts()
        history_digest = store.canonical_history_digest()
        dump_sha256, restored_dsn = _native_backup_restore(
            container=container_id,
            admin_dsn=admin_dsn,
            port=port,
            app_password=app_password,
        )
        restored = PostgresWritebackReceiverStore(restored_dsn)
        restored_counts = restored.counts()
        restored_history_digest = restored.canonical_history_digest()
        restored_before_replay = restored.counts()
        restored_replay = restored.receive(crash)
        restored_after_replay = restored.counts()
        flags = _role_flags(admin_dsn)
        checks = {
            "sequential_apply_once": first.disposition is WritebackReceiverDisposition.APPLIED,
            "exact_response_replay": replay.disposition is WritebackReceiverDisposition.REPLAYED,
            "same_key_payload_conflict_refused": conflict_refused,
            "eight_processes_converged": True,
            "one_concurrent_effect": dispositions.count("applied") == 1,
            "crash_after_commit_replayed": crash_replay.disposition is WritebackReceiverDisposition.REPLAYED,
            "receipt_mutation_refused": update_refused,
            "effect_mutation_refused": delete_refused,
            "malformed_direct_insert_refused": malformed_insert_refused,
            "non_privileged_role": not any(flags.values()),
            "three_receipts_equal_three_effects": counts.receipts == counts.effects == 3,
            "native_dump_listed": len(dump_sha256) == 64,
            "independent_restore_equal": restored_counts == counts,
            "restored_history_digest_equal": restored_history_digest == history_digest,
            "restored_replay_created_no_effect": restored_before_replay == restored_after_replay,
            "restored_replay_exact": restored_replay.response == crash_replay.response,
        }
        if not all(checks.values()):
            raise ReceiverMatrixError("PostgreSQL receiver observation contains a failed check")
        observation = {
            "runtime": {
                "docker_server": _run(("docker", "version", "--format", "{{.Server.Version}}"), capture=True),
                "image": image,
                "postgresql": postgresql,
                "python": platform.python_version(),
                "multiprocessing_start_method": context.get_start_method(),
                "application_role": flags,
            },
            "cases": {
                "sequential": {
                    "first_disposition": first.disposition.value,
                    "replay_disposition": replay.disposition.value,
                    "request_digest": sequential.request_digest,
                    "response_digest": first.response.response_digest,
                },
                "concurrent": {
                    "processes": 8,
                    "applied": dispositions.count("applied"),
                    "replayed": dispositions.count("replayed"),
                    "request_digest": concurrent.request_digest,
                    "response_digest": next(iter(response_digests)),
                },
                "crash_after_commit": {
                    "child_exit_code": crash_process.exitcode,
                    "retry_disposition": crash_replay.disposition.value,
                    "request_digest": crash.request_digest,
                    "response_digest": crash_replay.response.response_digest,
                },
            },
            "history": {
                "receipts": counts.receipts,
                "effects": counts.effects,
                "canonical_sha256": history_digest,
                "native_dump_sha256": dump_sha256,
                "restored_receipts": restored_counts.receipts,
                "restored_effects": restored_counts.effects,
                "restored_canonical_sha256": restored_history_digest,
            },
            "checks": checks,
        }
    finally:
        if container_id:
            actual = _run(("docker", "inspect", "--format", "{{.Id}}", container_id), capture=True)
            if actual != container_id:
                raise ReceiverMatrixError("PostgreSQL receiver cleanup identity mismatch")
            _run(("docker", "stop", "--time", "10", container_id))
            for _ in range(20):
                inspection = subprocess.run(  # nosec B603 - exact container identity
                    ("docker", "inspect", container_id),
                    cwd=ROOT,
                    shell=False,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                )
                if inspection.returncode != 0:
                    cleanup_complete = True
                    break
                time.sleep(0.25)
    if observation is None:
        raise ReceiverMatrixError("PostgreSQL receiver observation produced no evidence")
    if not cleanup_complete:
        raise ReceiverMatrixError("PostgreSQL receiver container cleanup was not verified")
    observation["checks"]["cleanup_complete"] = True
    return observation


def run_matrix(output: Path) -> dict[str, Any]:
    started = time.perf_counter()
    sqlite_report = json.loads(SQLITE_REPORT_PATH.read_text(encoding="utf-8"))
    sqlite_payload = dict(sqlite_report)
    sqlite_report_digest = str(sqlite_payload.pop("report_digest"))
    if sqlite_report_digest != _canonical_digest(sqlite_payload):
        raise ReceiverMatrixError("SQLite receiver report digest is invalid")
    runs = [
        run_observation(
            image=str(profile["image"]),
            expected_postgresql=str(profile["postgresql"]),
            prefix=str(profile["prefix"]),
        )
        for profile in PROFILES
    ]
    histories = {str(run["history"]["canonical_sha256"]) for run in runs}
    histories.add(str(sqlite_report["history"]["canonical_sha256"]))
    if len(histories) != 1:
        raise ReceiverMatrixError("SQLite/PostgreSQL receiver canonical history parity failed")
    if any(not all(bool(value) for value in run["checks"].values()) for run in runs):
        raise ReceiverMatrixError("PostgreSQL receiver matrix contains a failed check")
    report: dict[str, Any] = {
        "schema_version": "postgres-writeback-receiver-idempotency-matrix-v1",
        "executed_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "profile": "postgres-writeback-receiver-idempotency-matrix",
        "subject": {
            "base_commit": _base_commit(),
            "receiver_source_sha256": _source_digest(RECEIVER_SOURCE),
            "postgres_receiver_source_sha256": _source_digest(POSTGRES_RECEIVER_SOURCE),
            "matrix_runner_source_sha256": _source_digest(Path(__file__)),
            "sqlite_report_sha256": sqlite_report_digest,
            "supply_chain_policy_sha256": _source_digest(SUPPLY_CHAIN_POLICY_PATH),
        },
        "runs": runs,
        "parity": {
            "backends": ["sqlite", "postgresql-16.14", "postgresql-17.10"],
            "canonical_history_sha256": histories.pop(),
            "all_checks_passed": True,
            "all_cleanup_complete": True,
        },
        "limitations": [
            "single_docker_desktop_host",
            "two_sequential_single_node_postgresql_versions",
            "synthetic_digest_only_effects",
            "no_live_vendor_or_provider_status_contract",
            "no_cross_host_consensus_or_database_failover",
            "no_accounting_posting_or_production_claim",
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
        "postgres_writeback_receiver_idempotency_matrix=passed "
        f"report_digest={report['report_digest']} history_digest={report['parity']['canonical_history_sha256']}"
    )
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
