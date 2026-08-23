"""Prove durable write-back recovery observations on SQLite and PostgreSQL.

This is a disposable, provider-neutral persistence drill. It exercises the
same observation record, digest, idempotent insert, tenant/workspace scope,
and direct-mutation fences on the local SQLite implementation and exact
PostgreSQL 16.14/17.10 images. It never calls a provider and stores no payload
or secret.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess  # nosec B404 - fixed executable vectors below
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic.config import Config
from psycopg import Error as PsycopgError
from psycopg import connect, sql

from alembic import command
from reconforge.connectors.writeback import WritebackIntent
from reconforge.connectors.writeback_network import (
    WritebackProviderOutcome,
    WritebackRecoveryObservation,
    WritebackRecoveryObservationRecord,
)
from reconforge.db import connect as connect_sqlite
from reconforge.db import run_migrations
from reconforge.infrastructure.postgres_writeback import (
    PostgresWritebackIntentRepository,
    PostgresWritebackRecoveryObservationRepository,
)
from reconforge.infrastructure.sqlite_writeback import (
    SQLiteWritebackIntentRepository,
    SQLiteWritebackRecoveryObservationRepository,
)

ROOT = Path(__file__).resolve().parents[2]
POSTGRES_16_IMAGE = (
    "postgres:16-alpine@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777"
)
POSTGRES_17_IMAGE = (
    "postgres:17.10-alpine@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"
)
PROFILES = (
    (POSTGRES_16_IMAGE, "16.14", "rf-observation-pg16"),
    (POSTGRES_17_IMAGE, "17.10", "rf-observation-pg17"),
)
DATABASE = "reconforge_writeback_observations"
APP_ROLE = "reconforge_writeback_observations_app"
PASSWORD = secrets.token_urlsafe(24)
TENANT_ID = "e834-tenant"
WORKSPACE_ID = "e834-workspace"
INTENT_ID = "e834-intent"
CONNECTOR_ID = "reference-rest-writeback"
OPERATION = "payment.create"
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


class ObservationMatrixError(RuntimeError):
    """Raised when a closed observation persistence check fails."""


def _run(argv: tuple[str, ...], *, capture: bool = False) -> str:
    completed = subprocess.run(  # nosec B603 - shell-free fixed vectors
        argv,
        cwd=ROOT,
        shell=False,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=300,
    )
    if completed.returncode != 0:
        raise ObservationMatrixError("disposable PostgreSQL command failed")
    return completed.stdout.strip() if capture else ""


def _source_digest(path: Path) -> str:
    return hashlib.sha256(path.read_text(encoding="utf-8").replace("\r\n", "\n").encode()).hexdigest()


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _intent() -> WritebackIntent:
    return WritebackIntent(
        schema_version="connector-writeback-intent-v1",
        intent_id=INTENT_ID,
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        connector_id=CONNECTOR_ID,
        operation=OPERATION,
        payload_digest="a" * 64,
        idempotency_key="synthetic-recovery-idempotency",
        requested_by="e834-maker",
        requested_at=NOW,
        feature_enabled=True,
    )


def _observation(outcome: WritebackProviderOutcome, *, hour: int) -> WritebackRecoveryObservation:
    accepted = outcome is WritebackProviderOutcome.ACCEPTED
    return WritebackRecoveryObservation(
        outcome=outcome,
        idempotency_key="synthetic-recovery-idempotency",
        http_status=200 if accepted else 202,
        body_digest=("b" if accepted else "c") * 64,
        provider_reference="synthetic-e834-accepted" if accepted else None,
        provider_response_digest="d" * 64 if accepted else None,
    )


def _records(repository: Any) -> list[dict[str, Any]]:
    return [record.model_dump(mode="json") for record in repository.list_for_intent(intent_id=INTENT_ID, tenant_id=TENANT_ID, workspace_id=WORKSPACE_ID)]


def _sqlite_cell(directory: Path) -> dict[str, Any]:
    path = directory / "e834.sqlite3"
    run_migrations(path)
    with connect_sqlite(path) as connection:
        intent_repository = SQLiteWritebackIntentRepository(connection)
        observation_repository = SQLiteWritebackRecoveryObservationRepository(connection)
        intent_repository.put(_intent())
        pending = WritebackRecoveryObservationRecord.for_intent(
            _intent(), _observation(WritebackProviderOutcome.PENDING, hour=12), observed_by="e834-system", observed_at=NOW
        )
        accepted = WritebackRecoveryObservationRecord.for_intent(
            _intent(), _observation(WritebackProviderOutcome.ACCEPTED, hour=13), observed_by="e834-system", observed_at=NOW.replace(hour=13)
        )
        observation_repository.put(pending)
        observation_repository.put(accepted)
        observation_repository.put(pending)
        current = intent_repository.get(intent_id=INTENT_ID, tenant_id=TENANT_ID, workspace_id=WORKSPACE_ID)
        if current is None or current["intent"].status.value != "proposed":
            raise ObservationMatrixError("SQLite observation write changed lifecycle state")
        direct_update = False
        direct_delete = False
        try:
            connection.execute("UPDATE connector_writeback_recovery_observations SET observed_by='attacker'")
        except Exception:
            direct_update = True
            connection.rollback()
        try:
            connection.execute("DELETE FROM connector_writeback_recovery_observations")
        except Exception:
            direct_delete = True
            connection.rollback()
        rows = _records(observation_repository)
        if len(rows) != 2:
            raise ObservationMatrixError("SQLite observation replay did not converge")
        return {
            "engine": "sqlite",
            "records": rows,
            "records_digest": _digest(rows),
            "checks": {
                "idempotent_insert": True,
                "nonaccepted_preserves_intent": True,
                "direct_update_refused": direct_update,
                "direct_delete_refused": direct_delete,
                "tenant_scope_isolated": observation_repository.list_for_intent(
                    intent_id=INTENT_ID, tenant_id="e834-other-tenant", workspace_id=WORKSPACE_ID
                ) == (),
            },
        }


def _dsn(port: str, database: str, *, user: str = "postgres") -> str:
    return f"postgresql://{user}:{PASSWORD}@127.0.0.1:{port}/{database}"


def _wait(dsn: str) -> None:
    for _ in range(120):
        try:
            with connect(dsn) as connection:
                connection.execute("SELECT 1")
            return
        except PsycopgError:
            time.sleep(0.5)
    raise ObservationMatrixError("disposable PostgreSQL did not become ready")


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
        connection.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(DATABASE), sql.Identifier(APP_ROLE)))


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


def _grant_boundary(dsn: str) -> None:
    with connect(dsn) as connection:
        connection.execute(sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(sql.Identifier(APP_ROLE)))
        for table in ("connector_writeback_intents", "connector_writeback_recovery_observations"):
            connection.execute(
                sql.SQL("GRANT SELECT, INSERT ON reconforge.{} TO {}").format(
                    sql.Identifier(table), sql.Identifier(APP_ROLE)
                )
            )


def _postgres_cell(image: str, expected_version: str, prefix: str, directory: Path) -> dict[str, Any]:
    if re.fullmatch(r"postgres:[a-z0-9.-]+@sha256:[0-9a-f]{64}", image) is None:
        raise ObservationMatrixError("PostgreSQL image is not digest-pinned")
    container = prefix + "-" + secrets.token_hex(6)
    container_id = ""
    cleaned = False
    try:
        container_id = _run(("docker", "run", "--detach", "--rm", "--name", container, "-e", f"POSTGRES_PASSWORD={PASSWORD}", "-p", "127.0.0.1::5432", image), capture=True)
        port = _run(("docker", "port", container, "5432/tcp"), capture=True).rsplit(":", 1)[-1]
        maintenance = _dsn(port, "postgres")
        _wait(maintenance)
        _create_database_and_role(maintenance)
        source = _dsn(port, DATABASE)
        _upgrade(source)
        with connect(source) as admin:
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s)", (TENANT_ID, "Synthetic E-834 tenant"))
        _grant_boundary(source)
        app_dsn = _dsn(port, DATABASE, user=APP_ROLE)
        with connect(app_dsn) as connection:
            intent_repository = PostgresWritebackIntentRepository(connection)
            observation_repository = PostgresWritebackRecoveryObservationRepository(connection)
            intent_repository.put(_intent())
            pending = WritebackRecoveryObservationRecord.for_intent(
                _intent(), _observation(WritebackProviderOutcome.PENDING, hour=12), observed_by="e834-system", observed_at=NOW
            )
            accepted = WritebackRecoveryObservationRecord.for_intent(
                _intent(), _observation(WritebackProviderOutcome.ACCEPTED, hour=13), observed_by="e834-system", observed_at=NOW.replace(hour=13)
            )
            observation_repository.put(pending)
            observation_repository.put(accepted)
            observation_repository.put(pending)
            current = intent_repository.get(intent_id=INTENT_ID, tenant_id=TENANT_ID, workspace_id=WORKSPACE_ID)
            if current is None or current["intent"].status.value != "proposed":
                raise ObservationMatrixError("PostgreSQL observation write changed lifecycle state")
            records = _records(observation_repository)
            scope_isolated = observation_repository.list_for_intent(
                intent_id=INTENT_ID, tenant_id="e834-other-tenant", workspace_id=WORKSPACE_ID
            ) == ()
        direct_update = False
        direct_delete = False
        with connect(source) as admin:
            try:
                admin.execute("UPDATE reconforge.connector_writeback_recovery_observations SET observed_by='attacker'")
            except PsycopgError:
                direct_update = True
                admin.rollback()
            try:
                admin.execute("DELETE FROM reconforge.connector_writeback_recovery_observations")
            except PsycopgError:
                direct_delete = True
                admin.rollback()
            role = admin.execute(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname=%s",
                (APP_ROLE,),
            ).fetchone()
            version_row = admin.execute("SHOW server_version").fetchone()
            version = "" if version_row is None else str(version_row[0])
        if not role or version != expected_version:
            raise ObservationMatrixError("PostgreSQL runtime identity mismatch")
        result = {
            "engine": "postgresql",
            "postgresql": version,
            "image": image,
            "records": records,
            "records_digest": _digest(records),
            "role_flags": {
                "superuser": bool(role[0]),
                "create_database": bool(role[1]),
                "create_role": bool(role[2]),
                "replication": bool(role[3]),
                "bypass_rls": bool(role[4]),
            },
            "checks": {
                "idempotent_insert": True,
                "nonaccepted_preserves_intent": True,
                "direct_update_refused": direct_update,
                "direct_delete_refused": direct_delete,
                "tenant_scope_isolated": scope_isolated,
            },
        }
    finally:
        if container_id:
            inspected = _run(("docker", "inspect", "--format", "{{.Id}}", container), capture=True)
            if inspected != container_id:
                raise ObservationMatrixError("refusing to stop an unexpected Docker container")
            _run(("docker", "stop", container))
            probe = subprocess.run(("docker", "inspect", container), cwd=ROOT, shell=False, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)  # nosec B603
            cleaned = probe.returncode != 0
    if not cleaned:
        raise ObservationMatrixError("PostgreSQL container cleanup was not verified")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "docs/execution/POSTGRES_WRITEBACK_OBSERVATION_MATRIX_2026-08-22.json")
    args = parser.parse_args()
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="reconforge-e834-") as directory:
        temporary = Path(directory)
        results = [_sqlite_cell(temporary)]
        results.extend(_postgres_cell(*profile, temporary) for profile in PROFILES)
    digests = {str(result["records_digest"]) for result in results}
    if len(digests) != 1 or any(not all(bool(value) for value in result["checks"].values()) for result in results):
        raise ObservationMatrixError("observation matrix parity or a closed check failed")
    report = {
        "schema_version": "postgres-writeback-observation-matrix-v1",
        "executed_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "subject": {
            "base_commit": _run(("git", "rev-parse", "HEAD"), capture=True),
            "writeback_network_source_sha256": _source_digest(ROOT / "reconforge/connectors/writeback_network.py"),
            "sqlite_source_sha256": _source_digest(ROOT / "reconforge/infrastructure/sqlite_writeback.py"),
            "postgres_source_sha256": _source_digest(ROOT / "reconforge/infrastructure/postgres_writeback.py"),
            "sqlite_migration_version": 43,
            "postgres_revision": "0090_pg_writeback_observations",
        },
        "records_digest": next(iter(digests)),
        "results": results,
        "limitations": [
            "single Docker host and one failure domain",
            "synthetic provider-status observations only",
            "no live vendor, accounting posting, settlement, or production credential evidence",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "records_digest": report["records_digest"], "duration_seconds": report["duration_seconds"]}, sort_keys=True))


if __name__ == "__main__":
    main()
