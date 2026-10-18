"""Native populated AR restore preserves retained policy and raw write denials."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.application.receivables import ReceiptAllocationInput, ReceivableInvoiceLineInput
from reconforge.infrastructure.postgres import set_local_tenant_scope
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from tests.test_receivables_policy_raw_guards import (
    FORGED_POLICIES,
    LEGACY_MUTATIONS,
    TABLES,
    TENANT,
    RawDatabase,
    line,
    reject_forged_policy,
)
from tests.test_receivables_policy_raw_guards import isolated_postgres_migration_dsn as isolated_postgres_migration_dsn
from tests.test_receivables_policy_raw_guards import postgres_raw_policy as postgres_raw_policy


def test_live_native_populated_receivables_policy_restore(postgres_raw_policy: RawDatabase, tmp_path: Path) -> None:
    import psycopg
    from alembic.config import Config
    from psycopg import sql

    from alembic import command

    container = os.environ.get("RECONFORGE_TEST_NATIVE_POSTGRES_CONTAINER")
    local = all(shutil.which(tool) for tool in ("pg_dump", "pg_restore"))
    if not local and not container:
        pytest.skip("requires native pg_dump/pg_restore or an explicitly owned synthetic Docker container; PROD033 reviewed 2026-10-03")
    # Fixture seeds legacy at0098 then applies current installer SQL. Record the
    # frozen migration as well; applying it is idempotent and invents no values.
    postgres_raw_policy.connection.commit()
    command.upgrade(Config("alembic.ini"), "0099_pg_receivables_policy")
    set_local_tenant_scope(postgres_raw_policy.connection, TENANT, workspace_id="workspace")
    source = postgres_raw_policy.connection.info.dbname
    parameters = psycopg.conninfo.conninfo_to_dict(os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"])
    source_admin = psycopg.conninfo.make_conninfo(**{**parameters, "dbname": source})
    repo = PostgresReceivablesRepository(postgres_raw_policy.connection, TENANT)
    # The fixture retains USD history; exercise independent0/3-place captures.
    with psycopg.connect(source_admin) as admin:
        for currency, precision in (("JPY", 0), ("KWD", 3)):
            admin.execute("INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES(%s,%s,'Synthetic',%s)", (TENANT, currency, precision))
    saved = {}
    for currency, precision in (("JPY", 0), ("KWD", 3)):
        customer = repo.upsert_customer(customer_code=currency, name="Synthetic", currency_code=currency, credit_limit_minor=10000, workspace="Synthetic", actor_label="maker")
        document = repo.create_invoice(invoice_number=currency, customer_code=currency, currency_code=currency, invoice_date="2026-10-01", tax_minor=0, lines=[ReceivableInvoiceLineInput("Synthetic", "1", 1234, 1234)], workspace="Synthetic", actor_label="maker")
        repo.submit_invoice(document["id"], expected_version=1, actor_label="maker")
        repo.approve_invoice(document["id"], expected_version=2, actor_label="checker")
        receipt = repo.post_receipt(receipt_number=currency, customer_code=currency, currency_code=currency, receipt_date="2026-10-03", amount_minor=1000, allocations=[ReceiptAllocationInput(document["id"], 500)], workspace="Synthetic", actor_label="cashier")
        assert customer["monetary_policy"]["precision"] == precision
        saved[currency] = (document["id"], receipt["id"], receipt["monetary_policy"])
    postgres_raw_policy.connection.commit()

    def native(tool: str, args: list[str], data: bytes | None = None) -> bytes:
        environment = {**os.environ, "PGUSER": parameters["user"], "PGPASSWORD": parameters.get("password", "")}
        if local:
            environment.update(PGHOST=parameters["host"], PGPORT=parameters.get("port", "5432"))
            argv = [tool, *args]
        else:
            argv = ["docker", "exec", "-i", "-e", "PGPASSWORD", str(container), tool, "--host", "127.0.0.1", "--username", parameters["user"], *args]
        completed = subprocess.run(argv, input=data, capture_output=True, env=environment, timeout=120, check=False)
        assert completed.returncode == 0, completed.stderr.decode(errors="replace")
        return completed.stdout

    def retained(connection):
        values = {}
        for table in (*TABLES, "ar_idempotency_keys", "currency_registry_snapshots", "currency_registry_bindings", "domain_audit_events", "domain_audit_ledger_state", "outbox_events"):
            rows = connection.execute(sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier("reconforge", table))).fetchall()
            payload = sorted(json.dumps(row[0], sort_keys=True, separators=(",", ":")) for row in rows)
            values[table] = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
        return values

    target = "reconforge_ar_restore_" + uuid4().hex[:20]
    with psycopg.connect(source_admin, autocommit=True) as admin:
        before = retained(admin)
        dump = native("pg_dump", ["--format=custom", "--dbname", source])
        assert dump.startswith(b"PGDMP")
        assert admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (target,)).fetchone() is None
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
    evidence = {"target": "0099_pg_receivables_policy", "dump_sha256": hashlib.sha256(dump).hexdigest(), "dump_bytes": len(dump), "table_digests": before, "cleanup": False}
    try:
        native("pg_restore", ["--exit-on-error", "--no-owner", "--dbname", target], dump)
        restored_admin = psycopg.conninfo.make_conninfo(**{**parameters, "dbname": target})
        with psycopg.connect(restored_admin) as admin:
            assert retained(admin) == before
            assert admin.execute("SELECT version_num FROM alembic_version").fetchone() == ("0099_pg_receivables_policy",)
        app = psycopg.conninfo.conninfo_to_dict(os.environ["RECONFORGE_TEST_POSTGRES_DSN"])
        with psycopg.connect(**{**app, "dbname": target}) as connection:
            set_local_tenant_scope(connection, TENANT, workspace_id="workspace")
            connection.execute("SET LOCAL search_path TO reconforge,pg_catalog")
            assert connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone() == (False, False)
            restored_repo = PostgresReceivablesRepository(connection, TENANT)
            assert restored_repo.get_customer("legacy")["monetary_policy"]["status"] == "unverified"
            for invoice_id, receipt_id, policy in saved.values():
                assert restored_repo.get_invoice(invoice_id)["outstanding_minor"] == 734
                cash = restored_repo.get_receipt(receipt_id)
                assert cash["unallocated_minor"] == 500 and cash["monetary_policy"] == policy
            database = RawDatabase(connection, "workspace", postgres=True)
            for statement in LEGACY_MUTATIONS.values():
                database.deny(lambda statement=statement: connection.execute(statement))
            database.deny(lambda: line(database, "extra", "invoice", 2))
            for currency, field, value in FORGED_POLICIES:
                reject_forged_policy(database, currency, field, value)
            connection.rollback()
        with psycopg.connect(source_admin) as admin:
            assert retained(admin) == before
        evidence.update(values_equal=True, source_data_unchanged=True, legacy_raw_denials=len(LEGACY_MUTATIONS)+1, forged_tuple_denials=len(FORGED_POLICIES))
    finally:
        with psycopg.connect(source_admin, autocommit=True) as admin:
            admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()", (target,))
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(target)))
            evidence["cleanup"] = admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (target,)).fetchone() is None
        (tmp_path / "native-ar-policy-restore.json").write_text(json.dumps(evidence, indent=2)+"\n", encoding="utf-8")
        retained_output = os.environ.get("RECONFORGE_AR_POLICY_NATIVE_REPORT")
        if retained_output:
            Path(retained_output).write_text(json.dumps(evidence, indent=2)+"\n", encoding="utf-8")
