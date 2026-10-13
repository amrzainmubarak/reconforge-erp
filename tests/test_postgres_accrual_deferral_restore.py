"""Actual populated native restore continues an immutable paid-original schedule."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings
from tests.accrual_deferral_restore_catalog import retained_catalog
from tests.test_postgres_accrual_deferral import (
    ScheduleRuntime,
    accrual_deferral_database,
    logical_catalog,
    native_balances,
    paid_original,
    preparation,
    publish,
    pytestmark,
    receipt_database,
    runtime,
    write_original,
)
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime

__all__ = ["accrual_deferral_database", "pytestmark", "receipt_database", "runtime"]


def native(container: str, tool: str, database: str, data: bytes | None = None) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}", container) or not re.fullmatch(r"reconforge_(?:irp|ad1_restore)_[0-9a-f]{12}", database):
        raise ValueError("Exact supplied container and owned fixture database are required")
    flags = {"pg_dump": ["--format=custom"], "pg_restore": ["--exit-on-error", "--no-owner"]}
    if tool not in flags:
        raise ValueError("Unsupported native archive tool")
    inspected = subprocess.run(["docker", "container", "inspect", "--format", "{{.Id}}", container], capture_output=True, timeout=10, check=False)
    if inspected.returncode or inspected.stdout.decode().strip() != container:
        raise ValueError("The supplied native container identity could not be verified")
    result = subprocess.run(["docker", "exec", "-i", container, tool, "-U", "postgres", *flags[tool], "--dbname", database],
        input=data, capture_output=True, timeout=90, check=False)
    if result.returncode:
        raise ValueError(f"Native archive refused: tool={tool}, exit={result.returncode}, stderr_sha256={hashlib.sha256(result.stderr).hexdigest()}")
    return result.stdout


def history(connection: Any) -> dict[str, Any]:
    from psycopg import sql

    tables = [row[0] for row in connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='reconforge' ORDER BY tablename")]
    result = {}
    for table in tables:
        rows = sorted(json.dumps(row[0], sort_keys=True, separators=(",", ":"), ensure_ascii=False) for row in
            connection.execute(sql.SQL("SELECT to_jsonb(row_) FROM {} row_").format(sql.Identifier("reconforge", table))))
        result[table] = {"rows": len(rows), "sha256": hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()}
    return {"tables": result, "revision": connection.execute("SELECT version_num FROM alembic_version").fetchone()[0], "catalog": logical_catalog(connection)}


def test_actual_native_original_namespace_boundary_preserves_ordinary_voucher_and_refuses_billing_numbers_and_ids(runtime: ScheduleRuntime) -> None:
    from reconforge.domain.accrual_deferral import RESERVED_ORIGINALS

    original = paid_original(runtime)
    with runtime.actor("maker") as (connection, repository, _):
        entry = original["snapshot"]["entry"]
        assert connection.execute("SELECT reconforge.ad1_original_namespace_allowed(%s,%s) AS allowed", (entry["entry_number"], entry["id"])).fetchone()["allowed"] is True
        for prefix in RESERVED_ORIGINALS:
            for retained in (prefix + "a" * 32, prefix.lower() + "a" * 32):
                for number, identifier in ((retained, entry["id"]), (entry["entry_number"], retained)):
                    assert connection.execute("SELECT reconforge.ad1_original_namespace_allowed(%s,%s) AS allowed", (number, identifier)).fetchone()["allowed"] is False
        assert repository.owner.posting._get_effect(original["id"]) == original


def test_actual_populated_restore_preserves_original_cash_claims_and_resumes_remaining_tranches(runtime: ScheduleRuntime) -> None:
    import psycopg
    from psycopg import sql

    container = os.environ["RECONFORGE_TEST_POSTGRES_CONTAINER"]
    original = paid_original(runtime, dimensions=True)
    request = replace(preparation("attach_paid_expense"), original_effect_id=original["id"])
    with runtime.actor("maker") as (_, repository, actor):
        prepared = repository.prepare_source(request, command_id="restore-source", actor=actor)
    source = publish(runtime, prepared, "restore-source")
    with runtime.actor("maker") as (_, repository, actor):
        first = repository.prepare_tranche(source["source_id"], tranche_id="T1", command_id="restore-T1", actor=actor)
    publish(runtime, first, "restore-T1")
    with runtime.actor("maker") as (_, repository, actor):
        original_evidence = repository.evidence(source["source_id"], actor=actor)
    params = psycopg.conninfo.conninfo_to_dict(runtime.base.admin_dsn)
    source_database = params["dbname"]
    target = "reconforge_ad1_restore_" + uuid4().hex[:12]
    control = psycopg.conninfo.make_conninfo(runtime.base.admin_dsn, dbname="postgres")
    with psycopg.connect(runtime.base.admin_dsn) as admin:
        before = history(admin)
    archive = native(container, "pg_dump", source_database)
    assert archive.startswith(b"PGDMP")
    archive_path = Path(__file__).resolve().parents[1] / "output/m2-accrual-deferral/private" / ("populated-restore-original-" + uuid4().hex + ".dump")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with archive_path.open("xb") as handle:
        handle.write(archive)
    with psycopg.connect(control, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
    try:
        native(container, "pg_restore", target, archive)
        restored_admin = psycopg.conninfo.make_conninfo(runtime.base.admin_dsn, dbname=target)
        with psycopg.connect(restored_admin) as admin:
            after = history(admin)
            if after != before:
                diagnostic = {"schema_version": "accrual-deferral-restore-catalog-difference-v1", "before": before, "after": after}
                path = Path(__file__).resolve().parents[1] / "output/m2-accrual-deferral" / ("restore-catalog-difference-" + uuid4().hex + ".json")
                with path.open("x", encoding="utf8") as handle:
                    json.dump(diagnostic, handle, sort_keys=True, separators=(",", ":"))
            assert after["tables"] == before["tables"] and after["revision"] == before["revision"]
            assert retained_catalog(after["catalog"]) == retained_catalog(before["catalog"])
        app_dsn = psycopg.conninfo.make_conninfo(runtime.base.factory.settings.dsn, dbname=target)
        factory = PostgresConnectionFactory(PostgresSettings(dsn=app_dsn, require_tls=False))
        restored = ScheduleRuntime(ReceiptRuntime(factory, restored_admin, runtime.base.tenant, runtime.base.password))
        with restored.actor("maker") as (connection, repository, actor):
            flags = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=session_user").fetchone()
            assert not flags["rolsuper"] and not flags["rolbypassrls"]
            assert repository.evidence(source["source_id"], actor=actor) == original_evidence
            assert repository.prepare_source(request, command_id="restore-source", actor=actor) == prepared
            assert repository.get_plan(prepared["id"], actor=actor) == source
            with pytest.raises(FinancePostingError), connection.transaction():
                repository.owner.posting.prepare_reversal(original["id"], command_id="restored-original-inverse", entry_number="ORDINARY-ORIGINAL-INVERSE",
                    period_id="p2", posting_date="2026-11-01", reason="Consumed source retains original inverse ownership", actor=actor)
        for tranche in ("T2", "T3"):
            with restored.actor("maker") as (_, repository, actor):
                remaining = repository.prepare_tranche(source["source_id"], tranche_id=tranche, command_id="restore-" + tranche, actor=actor)
            publish(restored, remaining, "restore-" + tranche)
        with restored.actor("maker") as (connection, repository, actor):
            final = repository.evidence(source["source_id"], actor=actor)
            assert len(final["native_effects"]) == 5
            assert native_balances(connection, restored.base.tenant) == {"PREPAID": 0, "EXPENSE": 10001, "CASH": -10001}
            assert repository.owner.posting._get_effect(original["id"]) == original
            assert all(claim["state"] == "Consumed" for claim in final["source"]["claims"])
            with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
                connection.execute("DELETE FROM reconforge.accrual_deferral_claim_events WHERE tenant_id=%s", (restored.base.tenant,))
            write_original(final, "actual-populated-restore-completed-paid-expense")
        metadata = {"schema_version": "accrual-deferral-populated-restore-v1", "dump_bytes": len(archive), "dump_sha256": hashlib.sha256(archive).hexdigest(),
            "original_archive_private": True, "original_archive_file": archive_path.name,
            "revision": before["revision"], "all_native_tables": len(before["tables"]), "histories_equal_before_resume": True,
            "selected_logical_catalog_equal_before_resume": True, "catalog_acl_ownership_compared": False,
            "catalog_before_sha256": hashlib.sha256(json.dumps(before["catalog"], sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "catalog_after_sha256": hashlib.sha256(json.dumps(after["catalog"], sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "catalog_equivalence": "exact-except-six-frozen-legacy-nested-and-reparse-v1",
            "native_effects_after_resume": 5, "cash_minor": -10001,
            "original_effect_unchanged": True, "runtime_superuser": False, "runtime_bypassrls": False, "benchmark": False}
        path = Path(__file__).resolve().parents[1] / "output/m2-accrual-deferral" / ("populated-restore-" + uuid4().hex + ".json")
        with path.open("x", encoding="utf8") as handle:
            json.dump(metadata, handle, sort_keys=True, separators=(",", ":"))
    finally:
        with psycopg.connect(control, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(target)))
            assert admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (target,)).fetchone() is None
