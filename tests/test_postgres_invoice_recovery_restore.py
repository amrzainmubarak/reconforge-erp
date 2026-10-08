"""Native restore retains verified invoice acknowledgements and source history."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.application.receivables import ReceiptAllocationInput
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings
from reconforge.platform.common import PlatformError
from tests.test_receivables_credit_integrity import ReceivablesDatabase
from tests.test_receivables_credit_integrity import database as database
from tests.test_receivables_invoice_recovery import body, seed, state
from tests.test_receivables_monetary_policy import SNAPSHOT
from tests.test_receivables_policy_capture import bind


@pytest.mark.parametrize("database", ["postgres"], indirect=True)
def test_native_restore_preserves_versioned_and_legacy_invoice_recovery(database: ReceivablesDatabase, tmp_path: Path) -> None:
    import psycopg
    from psycopg import sql

    container = os.environ.get("RECONFORGE_TEST_NATIVE_POSTGRES_CONTAINER")
    local = all(shutil.which(tool) for tool in ("pg_dump", "pg_restore"))
    if not local and not container:
        pytest.skip("requires native PostgreSQL tools or an explicitly owned synthetic container; PROD039 reviewed 2026-10-03")
    seed(database)
    saved = []
    with database.repository() as repo:
        for legacy in (False, True):
            request = body(invoice_number="LEGACY" if legacy else "VERSIONED", idempotency_key="legacy" if legacy else "versioned",
                           **({"due_date": "2026-10-10"} if legacy else {}))
            original = repo.create_invoice(**request)
            repo.submit_invoice(original["id"], expected_version=1, actor_label="maker")
            repo.approve_invoice(original["id"], expected_version=2, actor_label="checker")
            repo.post_receipt(receipt_number=request["invoice_number"], customer_code="PROOF", receipt_date="2026-10-03", currency_code="JPY", amount_minor=1101,
                              allocations=[ReceiptAllocationInput(original["id"], 1101)], actor_label="cashier")
            if legacy:
                with database.admin.transaction():
                    database.admin.execute("UPDATE reconforge.ar_idempotency_keys SET response_json=%s::jsonb WHERE tenant_id=%s AND idempotency_key=%s",
                                           (json.dumps(original), database.tenant, request["idempotency_key"]))
            saved.append((request, original))
        repo.upsert_customer(customer_code="PROOF", name="Synthetic", currency_code="JPY", credit_limit_minor=10000,
                             payment_terms_days=90, status="Suspended", actor_label="maker")
    changed = deepcopy(SNAPSHOT)
    changed["source"] = "Synthetic replacement after original creation"
    bind(database, changed)
    before = state(database)
    source_revisions = [
        tuple(row) for row in database.admin.execute("SELECT version_num FROM alembic_version").fetchall()
    ]
    assert len(source_revisions) == 1
    source_revision = source_revisions[0][0]
    parameters = psycopg.conninfo.conninfo_to_dict(os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"])
    source = database.admin.info.dbname
    control_dsn = psycopg.conninfo.make_conninfo(**{**parameters, "dbname": "postgres"})

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

    dump = native("pg_dump", ["--format=custom", "--dbname", source])
    assert dump.startswith(b"PGDMP")
    target = "reconforge_invoice_restore_" + uuid4().hex[:16]
    evidence = {"schema": source_revision, "source": source, "target": target,
                "dump_sha256": hashlib.sha256(dump).hexdigest(), "dump_bytes": len(dump),
                "financial_history_sha256": hashlib.sha256(before.encode()).hexdigest(), "cleanup": False}
    with psycopg.connect(control_dsn, autocommit=True) as control:
        assert control.execute("SELECT 1 FROM pg_database WHERE datname=%s", (target,)).fetchone() is None
        control.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
    try:
        native("pg_restore", ["--exit-on-error", "--no-owner", "--dbname", target], dump)
        app_dsn = psycopg.conninfo.make_conninfo(os.environ["RECONFORGE_TEST_POSTGRES_DSN"], dbname=target)
        admin_dsn = psycopg.conninfo.make_conninfo(**{**parameters, "dbname": target})
        with psycopg.connect(admin_dsn) as admin:
            assert admin.execute("SELECT version_num FROM alembic_version").fetchall() == source_revisions
            restored = ReceivablesDatabase(factory=PostgresConnectionFactory(PostgresSettings(dsn=app_dsn, require_tls=False)), tenant=database.tenant, admin=admin)
            assert state(restored) == before
            with restored.repository() as repo:
                assert tuple(repo.connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == (False, False)
                repo.connection.rollback()
                for request, original in saved:
                    assert repo.create_invoice(**{**request, "actor_label": "another-authorized-manager"}) == original
                    current = repo.get_invoice(original["id"])
                    assert current["status"] == "Paid" and current["outstanding_minor"] == 0
                    assert current["monetary_policy"] == original["monetary_policy"]
                with pytest.raises(PlatformError, match="omitted due-date"):
                    repo.create_invoice(**{**saved[1][0], "due_date": ""})
            assert state(restored) == before
        assert state(database) == before
        evidence.update(restored_history_equal=True, source_unchanged=True, versioned_and_legacy_recovered=True,
                        inactive_customer_and_registry_rebind_recovered=True, ambiguous_legacy_refused=True, runtime_role_nonowner=True)
    finally:
        with psycopg.connect(control_dsn, autocommit=True) as control:
            control.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(target)))
            evidence["cleanup"] = control.execute("SELECT 1 FROM pg_database WHERE datname=%s", (target,)).fetchone() is None
        (tmp_path / "native-invoice-recovery.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        retained = os.environ.get("RECONFORGE_AR_INVOICE_REPLAY_NATIVE_REPORT")
        if retained:
            Path(retained).write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
