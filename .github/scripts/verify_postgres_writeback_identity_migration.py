"""Verify write-back identity migration refusal and clean restore in Docker."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess  # nosec B404
import tempfile
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic.config import Config
from psycopg import Error as PsycopgError
from psycopg import connect
from psycopg.types.json import Jsonb
from sqlalchemy.exc import DBAPIError

from alembic import command
from reconforge.connectors.writeback import (
    WritebackIntent,
    WritebackPolicy,
    approve_writeback,
    dispatch_writeback,
)

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "postgres:17.10-alpine"
IMAGE_REFERENCE = f"{IMAGE}@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"
PASSWORD = secrets.token_urlsafe(24)
SOURCE_DATABASE = "reconforge_writeback_source"
RESTORED_DATABASE = "reconforge_writeback_restored"
SOURCE_REVISION = "0088_pg_currency_snapshot"
TARGET_REVISION = "0089_pg_writeback_identity"
EXPECTED_AUDIT_ERROR = "existing connector write-back history violates immutable proposal identity or lifecycle"
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
MIGRATION_PATH = ROOT / "alembic/versions/0089_postgres_writeback_proposal_identity.py"
SYNTHETIC_IDEMPOTENCY_KEY = "e826-" * 4


class DrillError(RuntimeError):
    """Raised when the disposable migration drill cannot prove its contract."""


def _run(
    argv: Sequence[str],
    *,
    capture: bool = False,
    expected_exit: int = 0,
) -> str:
    completed = subprocess.run(  # nosec B603
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
        raise DrillError("disposable PostgreSQL command failed")
    return completed.stdout.strip() if capture else ""


def _dsn(port: str, database: str) -> str:
    return f"postgresql://postgres:{PASSWORD}@127.0.0.1:{port}/{database}"


def _wait_for_postgres(dsn: str) -> None:
    for _ in range(60):
        try:
            with connect(dsn) as connection:
                connection.execute("SELECT 1")
            return
        except PsycopgError:
            time.sleep(0.5)
    raise DrillError("disposable PostgreSQL did not become ready")


def _upgrade(dsn: str, revision: str) -> None:
    previous = os.environ.get("RECONFORGE_POSTGRES_DSN")
    os.environ["RECONFORGE_POSTGRES_DSN"] = dsn
    try:
        command.upgrade(Config(str(ROOT / "alembic.ini")), revision)
    finally:
        if previous is None:
            os.environ.pop("RECONFORGE_POSTGRES_DSN", None)
        else:
            os.environ["RECONFORGE_POSTGRES_DSN"] = previous


def _revision(dsn: str) -> str:
    with connect(dsn) as connection:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    if row is None:
        raise DrillError("Alembic revision is missing")
    return str(row[0])


def _trigger_definition(dsn: str) -> str:
    with connect(dsn) as connection:
        row = connection.execute(
            """
            SELECT pg_get_triggerdef(oid, true)
            FROM pg_trigger
            WHERE tgrelid = 'reconforge.connector_writeback_intents'::regclass
              AND tgname = 'connector_writeback_intent_guard'
              AND NOT tgisinternal
            """
        ).fetchone()
    if row is None:
        raise DrillError("write-back trigger is missing")
    return str(row[0])


def _history(dsn: str) -> list[dict[str, Any]]:
    with connect(dsn) as connection:
        rows = connection.execute(
            """
            SELECT tenant_id,intent_id,workspace_id,version,status,intent_digest,intent_json
            FROM reconforge.connector_writeback_intents
            ORDER BY tenant_id,workspace_id,intent_id,version
            """
        ).fetchall()
    return [
        {
            "tenant_id": str(row[0]),
            "intent_id": str(row[1]),
            "workspace_id": str(row[2]),
            "version": int(row[3]),
            "status": str(row[4]),
            "intent_digest": str(row[5]),
            "intent_json": row[6],
        }
        for row in rows
    ]


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _source_digest(path: Path) -> str:
    canonical = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _migration_commit() -> str:
    relative = MIGRATION_PATH.relative_to(ROOT).as_posix()
    return _run(("git", "log", "-1", "--format=%H", "--", relative), capture=True)


def _report_digest(report: dict[str, Any]) -> str:
    return _canonical_digest({key: value for key, value in report.items() if key != "report_digest"})


def _intent_history() -> tuple[WritebackIntent, WritebackIntent, WritebackIntent]:
    proposed = WritebackIntent(
        schema_version="connector-writeback-intent-v1",
        intent_id="e826-writeback-intent",
        tenant_id="e826-tenant",
        workspace_id="e826-workspace",
        connector_id="reference-rest-readonly",
        operation="payment.create",
        payload_digest="a" * 64,
        idempotency_key=SYNTHETIC_IDEMPOTENCY_KEY,
        requested_by="e826-maker",
        requested_at=NOW,
        feature_enabled=True,
    )
    policy = WritebackPolicy(
        connector_id=proposed.connector_id,
        allowed_operations=frozenset({proposed.operation}),
        feature_enabled=True,
    )
    approved = approve_writeback(
        proposed,
        policy=policy,
        actor_id="e826-checker",
        approved_at=NOW,
        assurance="mfa",
        reason="synthetic independent migration review",
    )
    dispatched = dispatch_writeback(approved, policy=policy)
    drifted = dispatched.model_copy(update={"payload_digest": "f" * 64})
    return proposed, approved, drifted


def _insert_intent(dsn: str, intent: WritebackIntent, version: int) -> None:
    with connect(dsn) as connection:
        connection.execute(
            """
            INSERT INTO reconforge.connector_writeback_intents(
                tenant_id,intent_id,workspace_id,version,status,intent_digest,intent_json,created_at
            ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                intent.tenant_id,
                intent.intent_id,
                intent.workspace_id,
                version,
                intent.status.value,
                intent.digest,
                Jsonb(intent.model_dump(mode="json", exclude_none=False)),
                NOW,
            ),
        )


def _insert_tenant(dsn: str, tenant_id: str) -> None:
    with connect(dsn) as connection:
        connection.execute(
            "INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s)",
            (tenant_id, "Synthetic E-826 tenant"),
        )


def _assert_upgrade_refused(dsn: str) -> None:
    try:
        _upgrade(dsn, "head")
    except DBAPIError as exc:
        if EXPECTED_AUDIT_ERROR not in str(exc):
            raise DrillError("write-back migration failed for an unexpected reason") from exc
        return
    raise DrillError("write-back migration accepted drifted history")


def _assert_enhanced_guard_refuses_drift(dsn: str, intent: WritebackIntent) -> None:
    try:
        _insert_intent(dsn, intent, 3)
    except PsycopgError as exc:
        if "proposal identity is immutable" not in str(exc):
            raise DrillError("enhanced write-back guard failed for an unexpected reason") from exc
        return
    raise DrillError("enhanced write-back guard accepted proposal drift")


def _docker_exec(container: str, *argv: str) -> None:
    _run(("docker", "exec", "-e", f"PGPASSWORD={PASSWORD}", container, *argv))


def _write_report(output: Path, report: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    report["report_digest"] = _report_digest(report)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_observation(
    *,
    image_reference: str,
    expected_postgresql: str,
    container_prefix: str,
) -> dict[str, Any]:
    if re.fullmatch(r"postgres:[a-z0-9.-]+@sha256:[0-9a-f]{64}", image_reference) is None:
        raise DrillError("PostgreSQL runtime image must be digest-pinned")
    if re.fullmatch(r"[0-9]+\.[0-9]+", expected_postgresql) is None:
        raise DrillError("expected PostgreSQL version is invalid")
    if re.fullmatch(r"[a-z0-9-]{8,48}", container_prefix) is None:
        raise DrillError("disposable container prefix is invalid")
    container = container_prefix + "-" + os.urandom(6).hex()
    container_id = ""
    observation: dict[str, Any] | None = None
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
        _docker_exec(container, "createdb", "-U", "postgres", SOURCE_DATABASE)
        source_dsn = _dsn(port, SOURCE_DATABASE)
        _upgrade(source_dsn, SOURCE_REVISION)
        proposed, approved, drifted = _intent_history()
        _insert_tenant(source_dsn, proposed.tenant_id)
        _insert_intent(source_dsn, proposed, 1)
        _insert_intent(source_dsn, approved, 2)
        valid_history = _history(source_dsn)
        valid_history_digest = _canonical_digest(valid_history)
        legacy_trigger = _trigger_definition(source_dsn)
        if not all(token in legacy_trigger for token in ("BEFORE", "UPDATE", "DELETE")) or "INSERT" in legacy_trigger:
            raise DrillError("source trigger is not the expected pre-0089 guard")

        with tempfile.TemporaryDirectory(prefix="reconforge-e826-") as temporary:
            host_dump = Path(temporary) / "writeback-pre-drift.dump"
            # Randomized inside an isolated disposable container; no host
            # shared temporary path or untrusted name is used.
            container_dump = f"/tmp/reconforge-e826-{os.urandom(6).hex()}.dump"  # nosec B108
            _docker_exec(
                container,
                "pg_dump",
                "-U",
                "postgres",
                "-d",
                SOURCE_DATABASE,
                "-Fc",
                "-f",
                container_dump,
            )
            _docker_exec(container, "pg_restore", "--list", container_dump)
            _run(("docker", "cp", f"{container}:{container_dump}", str(host_dump)))
            dump_digest = hashlib.sha256(host_dump.read_bytes()).hexdigest()

            _insert_intent(source_dsn, drifted, 3)
            invalid_history = _history(source_dsn)
            invalid_history_digest = _canonical_digest(invalid_history)
            if invalid_history_digest == valid_history_digest:
                raise DrillError("drifted source history did not change its canonical digest")
            _assert_upgrade_refused(source_dsn)
            if _revision(source_dsn) != SOURCE_REVISION:
                raise DrillError("failed migration changed the source revision")
            if _canonical_digest(_history(source_dsn)) != invalid_history_digest:
                raise DrillError("failed migration changed source write-back history")
            if _trigger_definition(source_dsn) != legacy_trigger:
                raise DrillError("failed migration changed the source trigger")

            _docker_exec(container, "createdb", "-U", "postgres", RESTORED_DATABASE)
            _docker_exec(
                container,
                "pg_restore",
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                "-U",
                "postgres",
                "-d",
                RESTORED_DATABASE,
                container_dump,
            )
            restored_dsn = _dsn(port, RESTORED_DATABASE)
            if _canonical_digest(_history(restored_dsn)) != valid_history_digest:
                raise DrillError("restored pre-drift history does not match its backup")
            if _revision(restored_dsn) != SOURCE_REVISION:
                raise DrillError("restored pre-drift revision is incorrect")
            _upgrade(restored_dsn, "head")
            if _revision(restored_dsn) != TARGET_REVISION:
                raise DrillError("restored database did not reach migration head")
            if _canonical_digest(_history(restored_dsn)) != valid_history_digest:
                raise DrillError("successful migration changed valid write-back history")
            enhanced_trigger = _trigger_definition(restored_dsn)
            if not all(token in enhanced_trigger for token in ("BEFORE", "INSERT", "UPDATE", "DELETE")):
                raise DrillError("restored database is missing the enhanced write-back guard")
            _assert_enhanced_guard_refuses_drift(restored_dsn, drifted)

        postgres_version = ""
        with connect(maintenance_dsn) as connection:
            row = connection.execute("SHOW server_version").fetchone()
            postgres_version = "" if row is None else str(row[0])
        if postgres_version != expected_postgresql:
            raise DrillError("PostgreSQL runtime version does not match its declared profile")
        observation = {
            "runtime": {
                "docker_server": _run(("docker", "version", "--format", "{{.Server.Version}}"), capture=True),
                "image": image_reference,
                "postgresql": postgres_version,
                "source_revision": SOURCE_REVISION,
                "target_revision": TARGET_REVISION,
            },
            "history": {
                "valid_versions": len(valid_history),
                "invalid_versions": len(invalid_history),
                "valid_history_sha256": valid_history_digest,
                "invalid_history_sha256": invalid_history_digest,
                "pre_drift_dump_sha256": dump_digest,
            },
            "checks": {
                "pre_drift_dump_list_verified": True,
                "drifted_upgrade_refused": True,
                "failed_upgrade_revision_preserved": True,
                "failed_upgrade_history_preserved": True,
                "failed_upgrade_trigger_preserved": True,
                "pre_drift_restore_verified": True,
                "restored_upgrade_to_head": True,
                "successful_upgrade_history_preserved": True,
                "enhanced_insert_guard_refused_drift": True,
                "cleanup_complete": False,
            },
        }
    finally:
        if container_id:
            inspected = _run(("docker", "inspect", "--format", "{{.Id}}", container), capture=True)
            if inspected != container_id:
                raise DrillError("refusing to stop an unexpected Docker container")
            _run(("docker", "stop", container))
            check = subprocess.run(  # nosec B603
                ("docker", "inspect", container),
                cwd=ROOT,
                shell=False,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            cleanup_complete = check.returncode != 0
    if observation is None:
        raise DrillError("write-back identity migration drill did not produce evidence")
    if not cleanup_complete:
        raise DrillError("disposable PostgreSQL cleanup was not verified")
    observation["checks"]["cleanup_complete"] = True
    return observation


def run_drill(output: Path) -> dict[str, Any]:
    observation = run_observation(
        image_reference=IMAGE_REFERENCE,
        expected_postgresql="17.10",
        container_prefix="reconforge-writeback-migration",
    )
    report = {
        "schema_version": "postgres-writeback-identity-migration-drill-v1",
        "executed_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "profile": "disposable-postgresql-writeback-identity-migration",
        "subject": {
            "migration_commit": _migration_commit(),
            "migration_source_sha256": _source_digest(MIGRATION_PATH),
            "runner_source_sha256": _source_digest(Path(__file__)),
        },
        **observation,
        "limitations": [
            "single_disposable_postgresql_node",
            "synthetic_data_and_credentials_only",
            "one_postgresql_version",
            "no_live_provider_or_accounting_posting",
            "no_cross_host_ha_dr_or_production_claim",
        ],
    }
    _write_report(output, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    report = run_drill(arguments.output.resolve(strict=False))
    print(
        "postgres_writeback_identity_migration_drill=passed "
        f"source={report['runtime']['source_revision']} target={report['runtime']['target_revision']} "
        f"report_digest={report['report_digest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
