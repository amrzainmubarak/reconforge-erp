"""Real populated restore; original history, ACL, RLS, functions and objects close."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess  # nosec B404
from typing import Any
from uuid import uuid4

from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from tests.gfo_browser_restore import database_snapshot, digest
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime


def verify_restore(runtime: Any, source_id: str) -> dict[str, Any]:
    import psycopg
    from psycopg import sql

    container = os.environ.get("RECONFORGE_TEST_POSTGRES_CONTAINER", "")
    assert container, "Mandatory native restore requires the explicitly owned correctness container"
    original_db = psycopg.conninfo.conninfo_to_dict(runtime.base.admin_dsn)["dbname"]
    target = "reconforge_icfx_restore_" + uuid4().hex[:16]
    before = database_snapshot(runtime.base.admin_dsn)
    with runtime.actor("poster") as (_, repository, actor):
        original_report = repository.report(source_id, actor=actor)
        source = repository.get_source(source_id, actor=actor)
        original_evidence = {plan["id"]: digest(repository.evidence(plan["id"], actor=actor)) for plan in source["plans"]}
    dump = subprocess.run(["docker", "exec", container, "pg_dump", "--username=postgres", "--dbname=" + original_db, "--format=custom"],
        capture_output=True, check=True, timeout=120).stdout  # nosec B603 B607
    assert dump.startswith(b"PGDMP")
    admin_dsn = psycopg.conninfo.make_conninfo(runtime.base.admin_dsn, dbname=target)
    app_dsn = psycopg.conninfo.make_conninfo(runtime.base.factory.settings.dsn, dbname=target)
    created = False
    try:
        with psycopg.connect(runtime.base.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(target)))
            created = True
        subprocess.run(["docker", "exec", "-i", container, "pg_restore", "--username=postgres", "--exit-on-error", "--dbname=" + target],
            input=dump, capture_output=True, check=True, timeout=180)  # nosec B603 B607
        assert database_snapshot(admin_dsn) == before
        restored = type(runtime)(ReceiptRuntime(PostgresConnectionFactory(PostgresSettings(dsn=app_dsn, require_tls=False)), admin_dsn, runtime.base.tenant, runtime.base.password))
        with restored.actor("poster") as (connection, repository, actor):
            assert repository.report(source_id, actor=actor) == original_report
            assert {plan["id"]: digest(repository.evidence(plan["id"], actor=actor)) for plan in source["plans"]} == original_evidence
            flags = dict(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone())
            assert flags == {"rolsuper": False, "rolbypassrls": False}
            rejected = 0
            for statement in ("UPDATE reconforge.intercompany_fx_sources SET reference='TAMPER' WHERE tenant_id=%s",
                              "UPDATE reconforge.intercompany_fx_links SET reason='TAMPER' WHERE tenant_id=%s",
                              "UPDATE reconforge.intercompany_fx_commands SET request_digest='TAMPER' WHERE tenant_id=%s"):
                try:
                    with connection.transaction():
                        connection.execute(statement, (runtime.base.tenant,))
                        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
                except psycopg.errors.CheckViolation:
                    rejected += 1
            assert rejected == 3
        with psycopg.connect(app_dsn) as connection:
            assert connection.execute("SELECT count(*) FROM reconforge.intercompany_fx_sources").fetchone()[0] == 0
        with PostgresTenantBoundary(restored.base.factory).transaction(runtime.base.tenant, workspace_id="foreign", organization_id="org") as connection:
            assert connection.execute("SELECT count(*) n FROM reconforge.intercompany_fx_sources").fetchone()["n"] == 0
        with restored.actor("maker") as (_, repository, actor):
            original = source["plans"][0]
            from tests.test_postgres_intercompany_fx import preparation
            assert repository.prepare(preparation(), command_id="prepare-original", actor=actor)["plan_digest"] == original["plan_digest"]
        assert database_snapshot(admin_dsn) == before
        result = {"schema_version": "intercompany-fx-native-populated-restore-v2", "status": "passed", "head": before["head"],
            "table_count": len(before["tables"]), "all_table_snapshot_sha256": digest(before["tables"]), "table_row_hashes": before["tables"],
            "objects": before["objects"], "dump_sha256": hashlib.sha256(dump).hexdigest(), "dump_bytes": len(dump), "native_role": flags,
            "source_effect_evidence_hashes": original_evidence, "report_digest": original_report["report_digest"], "tamper_refusals": rejected,
            "unscoped_foreign_workspace_concealed": True, "exact_original_command_replayed": True, "performance_measurement": False}
    finally:
        if created:
            with psycopg.connect(runtime.base.admin_dsn, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(target)))
                assert admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (target,)).fetchone() is None
    result["owned_restore_database_removed"] = True
    if directory := os.environ.get("RECONFORGE_ICFX_PROOF_DIR"):
        from pathlib import Path
        Path(directory, "restore-" + uuid4().hex + ".json").write_text(json.dumps(result, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return result
