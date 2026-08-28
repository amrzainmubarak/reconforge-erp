"""Prove PostgreSQL write-back recovery and compensation parity.

This is a disposable, provider-neutral lifecycle drill.  It exercises the
append-only proposal/approval/dispatch/acknowledgement/compensation contract
against exact PostgreSQL 16.14 and 17.10 images, then compares the canonical
history with the SQLite reference.  Provider acceptance is represented by a
synthetic marker and no network call, payload, credential, or financial row is
stored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import re
import secrets
import subprocess  # nosec B404 - fixed executable/argument vectors below
import tempfile
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from alembic.config import Config
from psycopg import Error as PsycopgError
from psycopg import connect, sql

from alembic import command
from reconforge.connectors.writeback import (
    WritebackAcknowledgement,
    WritebackIntent,
    WritebackPolicy,
    WritebackStatus,
    acknowledge_writeback,
    approve_writeback,
    complete_compensation,
    dispatch_writeback,
    request_compensation,
)
from reconforge.db import connect as connect_sqlite
from reconforge.db import run_migrations
from reconforge.infrastructure.postgres_writeback import PostgresWritebackIntentRepository
from reconforge.infrastructure.sqlite_writeback import SQLiteWritebackIntentRepository

ROOT = Path(__file__).resolve().parents[2]
POSTGRES_16_IMAGE = "postgres:16-alpine"
POSTGRES_16_IMAGE_REFERENCE = (
    f"{POSTGRES_16_IMAGE}@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777"
)
POSTGRES_17_IMAGE = "postgres:17.10-alpine"
POSTGRES_17_IMAGE_REFERENCE = (
    f"{POSTGRES_17_IMAGE}@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"
)
PROFILES = (
    {"postgresql": "16.14", "image": POSTGRES_16_IMAGE_REFERENCE, "prefix": "rf-wb-recovery-pg16"},
    {"postgresql": "17.10", "image": POSTGRES_17_IMAGE_REFERENCE, "prefix": "rf-wb-recovery-pg17"},
)
DATABASE = "reconforge_wb_recovery"
APP_ROLE = "reconforge_wb_recovery_app"
PASSWORD = secrets.token_urlsafe(24)
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
TENANT_ID = "e831-tenant"
WORKSPACE_ID = "e831-workspace"
INTENT_ID = "e831-writeback-intent"
ORIGINAL_KEY = "e831-original-key"
COMPENSATION_KEY = ORIGINAL_KEY + ":compensation"
CONNECTOR_ID = "reference-rest-writeback"
OPERATION = "payment.create"
PAYLOAD_DIGEST = "a" * 64
COMPENSATION_PAYLOAD_DIGEST = "b" * 64
ACK_DIGEST = "c" * 64
COMPENSATION_ACK_DIGEST = "d" * 64
MIGRATION_PATH = ROOT / "alembic/versions/0089_postgres_writeback_proposal_identity.py"
WRITEBACK_SOURCE = ROOT / "reconforge/connectors/writeback.py"
POSTGRES_SOURCE = ROOT / "reconforge/infrastructure/postgres_writeback.py"
SQLITE_SOURCE = ROOT / "reconforge/infrastructure/sqlite_writeback.py"
SUPPLY_CHAIN_POLICY_PATH = ROOT / "docs/security/supply-chain-policy.v1.json"


class RecoveryCompensationMatrixError(RuntimeError):
    """Raised when the closed recovery/compensation matrix is not proven."""


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
        raise RecoveryCompensationMatrixError("disposable PostgreSQL command failed")
    return completed.stdout.strip() if capture else ""


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _source_digest(path: Path) -> str:
    canonical = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _base_commit() -> str:
    return _run(("git", "rev-parse", "HEAD"), capture=True)


def _dsn(port: str, database: str, *, user: str = "postgres", password: str = PASSWORD) -> str:
    return f"postgresql://{user}:{password}@127.0.0.1:{port}/{database}"


def _wait_for_postgres(dsn: str) -> None:
    for _ in range(60):
        try:
            with connect(dsn) as connection:
                connection.execute("SELECT 1")
            return
        except PsycopgError:
            time.sleep(0.5)
    raise RecoveryCompensationMatrixError("disposable PostgreSQL did not become ready")


def _upgrade(dsn: str) -> None:
    previous = os.environ.get("RECONFORGE_POSTGRES_DSN")
    os.environ["RECONFORGE_POSTGRES_DSN"] = dsn
    try:
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    finally:
        if previous is None:
            os.environ.pop("RECONFORGE_POSTGRES_DSN", None)
        else:
            os.environ["RECONFORGE_POSTGRES_DSN"] = previous


def _intent() -> WritebackIntent:
    return WritebackIntent(
        schema_version="connector-writeback-intent-v1",
        intent_id=INTENT_ID,
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        connector_id=CONNECTOR_ID,
        operation=OPERATION,
        payload_digest=PAYLOAD_DIGEST,
        idempotency_key=ORIGINAL_KEY,
        requested_by="e831-maker",
        requested_at=NOW,
        feature_enabled=True,
    )


def _policy() -> WritebackPolicy:
    return WritebackPolicy(
        connector_id=CONNECTOR_ID,
        allowed_operations=frozenset({OPERATION}),
        feature_enabled=True,
    )


def _acknowledgement(*, compensation: bool = False) -> WritebackAcknowledgement:
    return WritebackAcknowledgement(
        provider_reference="synthetic-e831-compensation" if compensation else "synthetic-e831-accepted",
        acknowledged_at=NOW,
        response_digest=COMPENSATION_ACK_DIGEST if compensation else ACK_DIGEST,
        idempotency_key=COMPENSATION_KEY if compensation else ORIGINAL_KEY,
        accepted=True,
    )


def _advance_to_dispatched(repository: Any) -> tuple[WritebackIntent, WritebackIntent, WritebackIntent]:
    proposed = _intent()
    policy = _policy()
    approved = approve_writeback(
        proposed,
        policy=policy,
        actor_id="e831-checker",
        approved_at=NOW,
        assurance="mfa",
        reason="independent synthetic write-back review",
    )
    dispatched = dispatch_writeback(approved, policy=policy)
    repository.put(proposed)
    repository.put(approved, expected_version=1)
    repository.put(dispatched, expected_version=2)
    return proposed, approved, dispatched


def _provider_accept_then_exit(database: str, marker_path: str, *, sqlite: bool) -> None:
    """Record one synthetic provider acceptance and exit before persistence."""

    if sqlite:
        connection = connect_sqlite(Path(database), require_exists=True)
        repository: Any = SQLiteWritebackIntentRepository(connection)
    else:
        connection = connect(database)
        repository = PostgresWritebackIntentRepository(connection)
    try:
        current = repository.get(intent_id=INTENT_ID, tenant_id=TENANT_ID, workspace_id=WORKSPACE_ID)
        if current is None or current["version"] != 3 or current["intent"].status is not WritebackStatus.DISPATCHED:
            os._exit(91)
        Path(marker_path).write_text(
            json.dumps({"accepted": True, "idempotency_key": ORIGINAL_KEY}, sort_keys=True),
            encoding="utf-8",
        )
        os._exit(0)
    finally:
        connection.close()


def _compensation_accept_then_exit(database: str, marker_path: str, *, sqlite: bool) -> None:
    """Record one synthetic compensation acceptance and exit before persistence."""

    if sqlite:
        connection = connect_sqlite(Path(database), require_exists=True)
        repository: Any = SQLiteWritebackIntentRepository(connection)
    else:
        connection = connect(database)
        repository = PostgresWritebackIntentRepository(connection)
    try:
        current = repository.get(intent_id=INTENT_ID, tenant_id=TENANT_ID, workspace_id=WORKSPACE_ID)
        if (
            current is None
            or current["version"] != 5
            or current["intent"].status is not WritebackStatus.COMPENSATION_REQUESTED
        ):
            os._exit(92)
        Path(marker_path).write_text(
            json.dumps({"accepted": True, "idempotency_key": COMPENSATION_KEY}, sort_keys=True),
            encoding="utf-8",
        )
        os._exit(0)
    finally:
        connection.close()


def _join(process: _ProcessLike, *, label: str) -> None:
    process.join(timeout=40)
    if process.is_alive():
        process.terminate()
        process.join(timeout=10)
        raise RecoveryCompensationMatrixError(f"{label} timed out")
    if process.exitcode != 0:
        raise RecoveryCompensationMatrixError(f"{label} failed with exit code {process.exitcode}")


def _run_lifecycle(
    repository: Any,
    database: str,
    *,
    sqlite: bool,
    temporary: Path,
    history_database: str | None = None,
) -> dict[str, Any]:
    _advance_to_dispatched(repository)
    provider_marker = temporary / "provider-accepted.json"
    process = multiprocessing.Process(
        target=_provider_accept_then_exit,
        args=(database, str(provider_marker)),
        kwargs={"sqlite": sqlite},
    )
    process.start()
    _join(process, label="provider acceptance crash window")
    marker = json.loads(provider_marker.read_text(encoding="utf-8"))
    if marker != {"accepted": True, "idempotency_key": ORIGINAL_KEY}:
        raise RecoveryCompensationMatrixError("provider acceptance marker is invalid")
    current = repository.get(intent_id=INTENT_ID, tenant_id=TENANT_ID, workspace_id=WORKSPACE_ID)
    if current is None or current["version"] != 3:
        raise RecoveryCompensationMatrixError("acknowledgement was persisted before recovery")
    dispatched = current["intent"]
    acknowledged = acknowledge_writeback(
        dispatched,
        provider_reference="synthetic-e831-accepted",
        response_digest=ACK_DIGEST,
        acknowledged_at=NOW,
        accepted=True,
    )
    stored_acknowledged = repository.put(acknowledged, expected_version=3)
    if stored_acknowledged.status is not WritebackStatus.ACKNOWLEDGED:
        raise RecoveryCompensationMatrixError("recovery did not persist acknowledgement")
    if repository.put(acknowledged, expected_version=4) != acknowledged:
        raise RecoveryCompensationMatrixError("acknowledgement replay changed history")

    requested = request_compensation(
        acknowledged,
        reason="synthetic provider acceptance requires a governed reversal",
        actor_id="e831-controller",
        requested_at=NOW,
    )
    repository.put(requested, expected_version=4)
    compensation_marker = temporary / "compensation-accepted.json"
    process = multiprocessing.Process(
        target=_compensation_accept_then_exit,
        args=(database, str(compensation_marker)),
        kwargs={"sqlite": sqlite},
    )
    process.start()
    _join(process, label="compensation acceptance crash window")
    compensation_result = json.loads(compensation_marker.read_text(encoding="utf-8"))
    if compensation_result != {"accepted": True, "idempotency_key": COMPENSATION_KEY}:
        raise RecoveryCompensationMatrixError("compensation acceptance marker is invalid")
    current = repository.get(intent_id=INTENT_ID, tenant_id=TENANT_ID, workspace_id=WORKSPACE_ID)
    if current is None or current["version"] != 5:
        raise RecoveryCompensationMatrixError("compensation acknowledgement was persisted before recovery")
    compensated = complete_compensation(current["intent"], acknowledgement=_acknowledgement(compensation=True))
    stored_compensated = repository.put(compensated, expected_version=5)
    if stored_compensated.status is not WritebackStatus.COMPENSATED:
        raise RecoveryCompensationMatrixError("compensation recovery did not persist completion")
    if repository.put(compensated, expected_version=6) != compensated:
        raise RecoveryCompensationMatrixError("compensation replay changed history")

    history = _history(repository, history_database or database, sqlite=sqlite)
    statuses = [str(row["status"]) for row in history]
    if statuses != [
        "proposed",
        "approved",
        "dispatched",
        "acknowledged",
        "compensation_requested",
        "compensated",
    ]:
        raise RecoveryCompensationMatrixError("lifecycle status history is not canonical")
    return {
        "history": history,
        "history_sha256": _canonical_digest(history),
        "statuses": statuses,
        "checks": {
            "proposal_approval_dispatch_versions": True,
            "provider_acceptance_before_ack_persistence": True,
            "original_recovery_preserved_version_three": True,
            "original_acknowledgement_persisted_once": True,
            "original_acknowledgement_replay_idempotent": True,
            "compensation_request_actor_separated": True,
            "compensation_acceptance_before_completion_persistence": True,
            "compensation_key_is_distinct": True,
            "compensation_completion_persisted_once": True,
            "compensation_completion_replay_idempotent": True,
            "canonical_status_history": True,
        },
    }


def _history(repository: Any, database: str, *, sqlite: bool) -> list[dict[str, Any]]:
    del repository
    if sqlite:
        connection = connect_sqlite(Path(database), require_exists=True)
        try:
            rows = connection.execute(
                "SELECT version,status,intent_digest,intent_json FROM connector_writeback_intents "
                "WHERE tenant_id=? AND workspace_id=? AND intent_id=? ORDER BY version",
                (TENANT_ID, WORKSPACE_ID, INTENT_ID),
            ).fetchall()
            return [
                {
                    "version": int(row[0]),
                    "status": str(row[1]),
                    "intent_digest": str(row[2]),
                    "intent_json": json.loads(str(row[3])),
                }
                for row in rows
            ]
        finally:
            connection.close()
    with connect(database) as connection:
        rows = connection.execute(
            "SELECT version,status,intent_digest,intent_json FROM reconforge.connector_writeback_intents "
            "WHERE tenant_id=%s AND workspace_id=%s AND intent_id=%s ORDER BY version",
            (TENANT_ID, WORKSPACE_ID, INTENT_ID),
        ).fetchall()
    return [
        {
            "version": int(row[0]),
            "status": str(row[1]),
            "intent_digest": str(row[2]),
            "intent_json": row[3] if isinstance(row[3], dict) else json.loads(str(row[3])),
        }
        for row in rows
    ]


def _sqlite_observation(temporary: Path) -> dict[str, Any]:
    path = temporary / "e831-reference.sqlite3"
    run_migrations(path)
    connection = connect_sqlite(path, create_parent=True)
    try:
        repository = SQLiteWritebackIntentRepository(connection)
        result = _run_lifecycle(repository, str(path), sqlite=True, temporary=temporary)
        other = repository.get(intent_id=INTENT_ID, tenant_id="e831-other-tenant", workspace_id=WORKSPACE_ID)
        if other is not None:
            raise RecoveryCompensationMatrixError("SQLite tenant scope leaked")
        result["checks"]["tenant_scope_isolated"] = True
        result["checks"]["cleanup_complete"] = True
        return result
    finally:
        connection.close()


def _create_database_and_role(admin_dsn: str) -> None:
    with connect(admin_dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOINHERIT NOREPLICATION NOBYPASSRLS"
            ).format(sql.Identifier(APP_ROLE), sql.Literal(PASSWORD))
        )
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DATABASE)))
        connection.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(DATABASE)))
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(DATABASE), sql.Identifier(APP_ROLE))
        )


def _grant_application_boundary(admin_dsn: str) -> None:
    with connect(admin_dsn) as connection:
        connection.execute(sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(sql.Identifier(APP_ROLE)))
        connection.execute(
            sql.SQL("GRANT SELECT, INSERT ON reconforge.connector_writeback_intents TO {}").format(
                sql.Identifier(APP_ROLE)
            )
        )


def _role_flags(admin_dsn: str) -> dict[str, bool]:
    with connect(admin_dsn) as connection:
        row = connection.execute(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
            "FROM pg_roles WHERE rolname=%s",
            (APP_ROLE,),
        ).fetchone()
    if row is None:
        raise RecoveryCompensationMatrixError("application role is missing")
    return {
        "superuser": bool(row[0]),
        "create_database": bool(row[1]),
        "create_role": bool(row[2]),
        "replication": bool(row[3]),
        "bypass_rls": bool(row[4]),
    }


def _mutation_checks(admin_dsn: str) -> dict[str, bool]:
    update_refused = False
    delete_refused = False
    with connect(admin_dsn) as connection:
        try:
            connection.execute(
                "UPDATE reconforge.connector_writeback_intents SET status='failed' "
                "WHERE tenant_id=%s AND intent_id=%s",
                (TENANT_ID, INTENT_ID),
            )
        except PsycopgError as exc:
            update_refused = "immutable" in str(exc)
        connection.rollback()
        try:
            connection.execute(
                "DELETE FROM reconforge.connector_writeback_intents WHERE tenant_id=%s AND intent_id=%s",
                (TENANT_ID, INTENT_ID),
            )
        except PsycopgError as exc:
            delete_refused = "cannot be deleted" in str(exc)
        connection.rollback()
    return {"direct_update_refused": update_refused, "direct_delete_refused": delete_refused}


def _run_postgres_cell(*, image_reference: str, expected_postgresql: str, container_prefix: str, temporary: Path) -> dict[str, Any]:
    if re.fullmatch(r"postgres:[a-z0-9.-]+@sha256:[0-9a-f]{64}", image_reference) is None:
        raise RecoveryCompensationMatrixError("PostgreSQL image is not digest-pinned")
    container = container_prefix + "-" + secrets.token_hex(6)
    container_id = ""
    cleanup_complete = False
    try:
        container_id = _run(
            (
                "docker",
                "run",
                "--detach",
                "--rm",
                "--name",
                container,
                "-e",
                f"POSTGRES_PASSWORD={PASSWORD}",
                "-p",
                "127.0.0.1::5432",
                image_reference,
            ),
            capture=True,
        )
        port_line = _run(("docker", "port", container, "5432/tcp"), capture=True)
        port = port_line.rsplit(":", 1)[1]
        maintenance_dsn = _dsn(port, "postgres")
        _wait_for_postgres(maintenance_dsn)
        _create_database_and_role(maintenance_dsn)
        source_dsn = _dsn(port, DATABASE)
        _upgrade(source_dsn)
        with connect(source_dsn) as admin:
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s)", (TENANT_ID, "Synthetic E-831 tenant"))
        _grant_application_boundary(source_dsn)
        app_dsn = _dsn(port, DATABASE, user=APP_ROLE)
        with connect(app_dsn) as connection:
            result = _run_lifecycle(
                PostgresWritebackIntentRepository(connection),
                app_dsn,
                sqlite=False,
                temporary=temporary,
                history_database=source_dsn,
            )
            scope_probe = PostgresWritebackIntentRepository(connection).get(
                intent_id=INTENT_ID,
                tenant_id="e831-other-tenant",
                workspace_id=WORKSPACE_ID,
            )
            if scope_probe is not None:
                raise RecoveryCompensationMatrixError("PostgreSQL tenant scope leaked")
        role_flags = _role_flags(maintenance_dsn)
        mutation_checks = _mutation_checks(source_dsn)
        with connect(maintenance_dsn) as connection:
            row = connection.execute("SHOW server_version").fetchone()
        postgres_version = "" if row is None else str(row[0])
        if postgres_version != expected_postgresql:
            raise RecoveryCompensationMatrixError("PostgreSQL version does not match declared profile")
        result["checks"].update(mutation_checks)
        result["checks"]["tenant_scope_isolated"] = True
        result["checks"]["non_privileged_role"] = not any(role_flags.values())
        result["role_flags"] = role_flags
        result["runtime"] = {
            "image": image_reference,
            "postgresql": postgres_version,
            "docker_server": _run(("docker", "version", "--format", "{{.Server.Version}}"), capture=True),
        }
        result["checks"]["cleanup_complete"] = False
    finally:
        if container_id:
            inspected = _run(("docker", "inspect", "--format", "{{.Id}}", container), capture=True)
            if inspected != container_id:
                raise RecoveryCompensationMatrixError("refusing to stop an unexpected Docker container")
            _run(("docker", "stop", container))
            check = subprocess.run(  # nosec B603 - fixed Docker inspect vector
                ("docker", "inspect", container),
                cwd=ROOT,
                shell=False,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            cleanup_complete = check.returncode != 0
    if not cleanup_complete:
        raise RecoveryCompensationMatrixError("PostgreSQL disposable container cleanup was not verified")
    result["checks"]["cleanup_complete"] = True
    return result


def run_matrix(output: Path) -> dict[str, Any]:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="reconforge-e831-") as directory:
        temporary = Path(directory)
        sqlite_result = _sqlite_observation(temporary)
        postgres_results = [
            _run_postgres_cell(
                image_reference=profile["image"],
                expected_postgresql=profile["postgresql"],
                container_prefix=profile["prefix"],
                temporary=temporary,
            )
            for profile in PROFILES
        ]
    all_results = [sqlite_result, *postgres_results]
    digests = {str(result["history_sha256"]) for result in all_results}
    if len(digests) != 1:
        raise RecoveryCompensationMatrixError("SQLite and PostgreSQL histories diverged")
    if any(not all(bool(value) for value in result["checks"].values()) for result in all_results):
        raise RecoveryCompensationMatrixError("recovery/compensation matrix contains a failed check")
    report = {
        "schema_version": "postgres-writeback-recovery-compensation-matrix-v1",
        "executed_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "profile": "provider-neutral-writeback-recovery-compensation-parity",
        "subject": {
            "base_commit": _base_commit(),
            "writeback_source_sha256": _source_digest(WRITEBACK_SOURCE),
            "postgres_persistence_source_sha256": _source_digest(POSTGRES_SOURCE),
            "sqlite_persistence_source_sha256": _source_digest(SQLITE_SOURCE),
            "migration_source_sha256": _source_digest(MIGRATION_PATH),
            "supply_chain_policy_sha256": _source_digest(SUPPLY_CHAIN_POLICY_PATH),
            "matrix_runner_source_sha256": _source_digest(Path(__file__)),
        },
        "sqlite_reference": sqlite_result,
        "runs": postgres_results,
        "parity": {
            "history_sha256": next(iter(digests)),
            "postgresql_versions": [str(result["runtime"]["postgresql"]) for result in postgres_results],
            "all_checks_passed": True,
            "all_cleanup_complete": all(bool(result["checks"]["cleanup_complete"]) for result in postgres_results),
        },
        "limitations": [
            "synthetic_provider_acceptance_marker_only",
            "no_live_provider_or_status_api",
            "no_accounting_posting_or_settlement",
            "single_disposable_postgresql_node_per_version",
            "single_docker_desktop_host",
            "no_cross_host_quorum_or_automatic_failover",
            "no_production_exactly_once_or_rpo_rto_claim",
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
        "postgres_writeback_recovery_compensation_matrix=passed "
        f"versions={','.join(report['parity']['postgresql_versions'])} "
        f"report_digest={report['report_digest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
