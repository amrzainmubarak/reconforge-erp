"""Original read view after real populated restore; no new financial effect."""

import hashlib
import json
import os
import runpy
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings
from reconforge.infrastructure.postgres_intercompany_cashflow import PostgresIntercompanyCashflowRepository
from tests.gfo_browser_restore import FINANCIAL_TABLES, database_snapshot
from tests.test_postgres_accrual_deferral_restore import native
from tests.test_postgres_intercompany_cashflow import opening, write_original
from tests.test_postgres_intercompany_fx import FxRuntime, cash, eliminate, recognize, revalue
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime

pytest_plugins = ("tests.test_postgres_intercompany_fx",)


def test_real_populated_archive_restores_exact_original_source_cashflow_without_financial_writes(runtime: FxRuntime) -> None:
    import psycopg
    from psycopg import sql

    original = recognize(runtime)
    basis = opening(runtime, original)
    cash(runtime, original["source_id"])
    revalue(runtime, original["source_id"])
    eliminate(runtime, original["source_id"])
    with runtime.actor("poster") as (connection, _, actor):
        expected = PostgresIntercompanyCashflowRepository(connection, runtime.base.tenant).evidence(
            original["source_id"], opening=basis, actor=actor)
    protected = tuple(dict.fromkeys((*FINANCIAL_TABLES, "intercompany_fx_sources", "intercompany_fx_plans",
        "intercompany_fx_reviews", "intercompany_fx_links", "intercompany_fx_post_evidence", "intercompany_fx_commands")))
    before = database_snapshot(runtime.base.admin_dsn, financial_tables=protected)
    container = os.environ["RECONFORGE_TEST_POSTGRES_CONTAINER"]
    source_database = psycopg.conninfo.conninfo_to_dict(runtime.base.admin_dsn)["dbname"]
    archive = native(container, "pg_dump", source_database)
    assert archive.startswith(b"PGDMP")
    directory = Path(os.environ["RECONFORGE_CASHFLOW_PROOF_DIR"])
    archive_path = directory / ("original-cashflow-populated-" + uuid4().hex + ".dump")
    with archive_path.open("xb") as handle:
        handle.write(archive)
    # Reuse the existing finite native archive helper's approved unique target
    # namespace, full-container inspection and exact supplied tool arguments.
    target = "reconforge_ad1_restore_" + uuid4().hex[:12]
    control = psycopg.conninfo.make_conninfo(runtime.base.admin_dsn, dbname="postgres")
    with psycopg.connect(control, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(target)))
    try:
        native(container, "pg_restore", target, archive)
        admin_dsn = psycopg.conninfo.make_conninfo(runtime.base.admin_dsn, dbname=target)
        after = database_snapshot(admin_dsn, financial_tables=protected)
        assert after == before  # Every row, catalog, ACL/owner, FORCE RLS; native CHECK reparse.
        app_dsn = psycopg.conninfo.make_conninfo(runtime.base.factory.settings.dsn, dbname=target)
        factory = PostgresConnectionFactory(PostgresSettings(dsn=app_dsn, require_tls=False))
        restored = FxRuntime(ReceiptRuntime(factory, admin_dsn, runtime.base.tenant, runtime.base.password))
        with restored.actor("poster") as (connection, owner, actor):
            actual = PostgresIntercompanyCashflowRepository(connection, restored.base.tenant).evidence(
                original["source_id"], opening=basis, actor=actor)
            assert actual == expected
            assert actual["native_role"] == {"rolsuper": False, "rolbypassrls": False}
            for statement in (
                "UPDATE reconforge.intercompany_fx_sources SET reference='TAMPER' WHERE tenant_id=%s",
                "UPDATE reconforge.intercompany_fx_links SET reason='TAMPER' WHERE tenant_id=%s",
                "UPDATE reconforge.intercompany_fx_commands SET request_digest=repeat('0',64) WHERE tenant_id=%s",
            ):
                with pytest.raises(psycopg.errors.CheckViolation) as refused, connection.transaction():
                    cursor = connection.execute(statement, (restored.base.tenant,))
                    assert cursor.rowcount > 0
                    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
                assert refused.value.diag.constraint_name == "intercompany_fx_owner"
            assert PostgresIntercompanyCashflowRepository(connection, restored.base.tenant).evidence(
                original["source_id"], opening=basis, actor=actor) == expected
            with pytest.raises(FinancePostingError), connection.transaction():
                owner.owner.posting.prepare_reversal(actual["cashflow"]["source_effect_ids"][0],
                    command_id="restored-detached-original", entry_number="ORDINARY-DETACHED-ORIGINAL", period_id="period",
                    posting_date="2026-10-07", reason="Original paired source inverse remains governed", actor=actor)
            oracle = runpy.run_path(str(Path(__file__).resolve().parents[1] / ".github/scripts/verify_intercompany_cashflow_oracle.py"))
            verified = oracle["verify"](actual)
            assert verified["closing_minor"] == verified["fx_on_cash_minor"] == 101 and verified["operating_net_minor"] == 0
            write_original(actual)
        with psycopg.connect(app_dsn) as connection:
            assert connection.execute("SELECT count(*) FROM reconforge.intercompany_fx_sources").fetchone()[0] == 0
        reread = database_snapshot(admin_dsn, financial_tables=protected)
        assert reread["objects"] == before["objects"] and reread["head"] == before["head"]
        assert all(reread["tables"][table] == before["tables"][table] for table in before["tables"] if table != "identity_users")
        metadata = {"schema_version": "intercompany-source-cashflow-populated-restore-v1", "head": before["head"],
            "all_native_tables": len(before["tables"]), "all_rows_equal_before_authentication": True,
            "logical_catalog_acl_owners_equal": True, "native_check_reparse": True,
            "dump_private": True, "dump_file": archive_path.name, "dump_bytes": len(archive), "dump_sha256": hashlib.sha256(archive).hexdigest(),
            "original_source_evidence_equal": True, "native_financial_writes": False, "tamper_refusals": 3,
            "unscoped_source_rows": 0, "remaining_mutation": "identity_users.last_login_at_on_restored_authentication",
            "independent_oracle": verified, "benchmark": False}
    finally:
        with psycopg.connect(control, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(target)))
            assert admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (target,)).fetchone() is None
    metadata["owned_restore_database_removed"] = True
    with (directory / ("original-cashflow-restore-metadata-" + uuid4().hex + ".json")).open("x") as handle:
        json.dump(metadata, handle, sort_keys=True, separators=(",", ":"), allow_nan=False)
