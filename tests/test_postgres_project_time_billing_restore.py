"""Real populated native AR recovery and distinct payroll/billing time custody.

The supplied root-owned service remains running. Each fixture owns only its
unique database; administrative dumps stay in memory and never enter evidence.
Ordered migration143 acceptance remains separate from directly installed
development schema when this module is executed in an isolated checkout.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from reconforge.domain.budget_control import BudgetScope
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings
from reconforge.infrastructure.postgres_budget_control import PostgresBudgetControlRepository
from reconforge.infrastructure.postgres_project_time_billing import PostgresProjectTimeBillingRepository
from tests.gfo_browser_restore import FINANCIAL_TABLES, database_snapshot
from tests.project_time_billing_browser import PROJECT_TIME_BILLING_TABLES
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_people_project_payroll import SCOPE, PeopleRuntime, approved_budget, commit
from tests.test_postgres_people_project_payroll import prepare as wage_prepare
from tests.test_postgres_project_time_billing import post, prepare, sources

pytest_plugins = ("tests.test_postgres_project_time_billing",)


def native(container: str, tool: str, database: str, data: bytes | None = None) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}", container) or not re.fullmatch(r"reconforge_(?:irp|pb_restore)_[0-9a-f]{12}", database):
        raise ValueError("Exact supplied root-owned container and fixture database required")
    tools = {"pg_dump": ["--format=custom"], "pg_restore": ["--exit-on-error", "--no-owner"]}
    if tool not in tools:
        raise ValueError("Only fixed native archive tools are supported")
    identity = subprocess.run(["docker", "container", "inspect", "--format", "{{.Id}}", container],
        capture_output=True, timeout=10, check=False)
    if identity.returncode or identity.stdout.decode().strip() != container:
        raise ValueError("Supplied service identity differs")
    result = subprocess.run(["docker", "exec", "-i", container, tool, "-U", "postgres", *tools[tool], "--dbname", database],
        input=data, capture_output=True, timeout=120, check=False)
    if result.returncode:
        raise ValueError(f"Native archive failed: tool={tool}, exit={result.returncode}, stderr_sha256={hashlib.sha256(result.stderr).hexdigest()}")
    return result.stdout


def original_json(value: Any) -> bytes:
    def temporal(item: Any) -> str:
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        raise TypeError("Original evidence requires an explicit JSON representation")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=temporal).encode()


def independently_verify(value: dict[str, Any]) -> dict[str, Any]:
    script = Path(__file__).resolve().parents[1] / ".github/scripts/verify_project_time_billing_cycle_oracle.py"
    spec = importlib.util.spec_from_file_location("restored_project_billing_independent_oracle", script)
    if spec is None or spec.loader is None:
        raise ValueError("Original independent financial oracle missing")
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
    return oracle.verify(json.loads(original_json(value)))


def collection(runtime: PeopleRuntime, invoice: dict[str, Any], amount: int, key: str) -> dict[str, Any]:
    with runtime.actor("maker", private=False) as (connection, _, actor):
        return PostgresProjectTimeBillingRepository(connection, runtime.base.tenant).prepare_collection(invoice["id"],
            amount_minor=amount, period_id="period", posting_date="2026-10-05", command_id=key, actor=actor)


def evidence(runtime: PeopleRuntime, invoice: dict[str, Any]) -> dict[str, Any]:
    with runtime.actor("maker", private=False) as (connection, _, actor):
        return PostgresProjectTimeBillingRepository(connection, runtime.base.tenant).evidence(invoice["id"], actor=actor)


def test_populated_billing_restore_preserves_original_ar_claims_and_resumes_final_collection(billing: PeopleRuntime) -> None:
    import psycopg
    from psycopg import sql

    times, prices = sources(billing)
    invoice = prepare(billing, times, prices, "restore-invoice")
    posted_invoice = post(billing, invoice, "restore-invoice")
    partial = collection(billing, invoice, 1000, "restore-partial")
    posted_partial = post(billing, partial, "restore-partial")
    original = evidence(billing, invoice)
    assert original["ar_invoice"]["outstanding_minor"] == 5236
    selected = tuple(dict.fromkeys(FINANCIAL_TABLES + PROJECT_TIME_BILLING_TABLES))
    before = database_snapshot(billing.base.admin_dsn, financial_tables=selected)
    container = os.environ["RECONFORGE_TEST_POSTGRES_CONTAINER"]
    source_database = psycopg.conninfo.conninfo_to_dict(billing.base.admin_dsn)["dbname"]
    archive = native(container, "pg_dump", source_database)
    assert archive.startswith(b"PGDMP")
    name = "reconforge_pb_restore_" + uuid4().hex[:12]
    control = psycopg.conninfo.make_conninfo(billing.base.admin_dsn, dbname="postgres")
    with psycopg.connect(control, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
    try:
        native(container, "pg_restore", name, archive)
        admin_dsn = psycopg.conninfo.make_conninfo(billing.base.admin_dsn, dbname=name)
        after = database_snapshot(admin_dsn, financial_tables=selected)
        assert after == before  # All rows, logical catalogs, owners, ACL, FORCE RLS; native CHECK reparse.
        ordinary = PostgresConnectionFactory(PostgresSettings(dsn=psycopg.conninfo.make_conninfo(billing.base.factory.settings.dsn, dbname=name), require_tls=False))
        private = PostgresConnectionFactory(PostgresSettings(dsn=psycopg.conninfo.make_conninfo(billing.private.settings.dsn, dbname=name), require_tls=False))
        restored = PeopleRuntime(ReceiptRuntime(ordinary, admin_dsn, billing.base.tenant, billing.base.password), private)
        with restored.actor("maker", private=False) as (connection, _, actor):
            flags = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=session_user").fetchone()
            assert flags["rolsuper"] is False and flags["rolbypassrls"] is False
            assert connection.execute("SELECT pg_has_role(session_user,'reconforge_personnel_runtime','MEMBER') AS member").fetchone()["member"] is False
            for table in ("hc_employee_private", "hc_rates", "hc_payrun_private", "hc_payment_private"):
                assert connection.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier("reconforge", table))).fetchone()["n"] == 0
            repository = PostgresProjectTimeBillingRepository(connection, restored.base.tenant)
            assert repository.evidence(invoice["id"], actor=actor) == original
            assert repository.get(invoice["id"], actor=actor) == posted_invoice
            assert repository.get(partial["id"], actor=actor) == posted_partial
        assert collection(restored, invoice, 1000, "restore-partial") == partial
        with pytest.raises(FinancePostingError):
            prepare(restored, times, prices, "restored-double-time")
        with restored.actor("poster", private=False) as (connection, _, _):
            for statement in ("DELETE FROM reconforge.pb_time_claims WHERE tenant_id=%s",
                              "UPDATE reconforge.ar_invoices SET pb_owner_id=NULL WHERE tenant_id=%s AND pb_owner_id IS NOT NULL",
                              "UPDATE reconforge.pb_plans SET amount_minor=amount_minor+1 WHERE tenant_id=%s"):
                with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
                    connection.execute(statement, (restored.base.tenant,))
        final = collection(restored, invoice, 5236, "restore-final")
        post(restored, final, "restore-final")
        proof = evidence(restored, invoice)
        independent = independently_verify(proof)
        assert independent["accepted_cycle"] and independent["native_effects"] == 3
        assert independent["amount_minor"] == independent["collected_minor"] == 6236 and independent["outstanding_minor"] == 0
        record = {"schema_version": "project-billing-populated-restore-v1", "source_invoice_id": invoice["id"],
            "native_archive_bytes": len(archive), "native_archive_sha256": hashlib.sha256(archive).hexdigest(),
            "administrative_archive_retained": False, "before_authentication_snapshot": before,
            "native_catalog_equivalence": "exact logical catalogs including ACL/owners; PostgreSQL-native CHECK reparse",
            "original_evidence_sha256": hashlib.sha256(original_json(original)).hexdigest(),
            "independent_financial_oracle": independent, "original_evidence_after_resume": json.loads(original_json(proof)),
            "ordinary_personnel_member": False, "ordinary_private_rows": 0,
            "migration_head": before["head"], "bank_execution_proven": False, "benchmark": False}
        directory = Path(__file__).resolve().parents[1] / "output/project-billing-restores"
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / ("original-" + uuid4().hex + ".json")).open("x", encoding="utf8") as handle:
            json.dump(record, handle, sort_keys=True, separators=(",", ":"), allow_nan=False)
    finally:
        with psycopg.connect(control, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            assert admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone() is None


def test_payroll_and_billing_claim_the_same_approved_whole_time_in_distinct_native_namespaces(billing: PeopleRuntime) -> None:
    from psycopg import sql

    times, prices = sources(billing)
    budget = approved_budget(billing)
    invoice = prepare(billing, times, prices, "distinct-billing")
    wage = wage_prepare(billing, times, budget, "distinct-wage")
    post(billing, invoice, "distinct-invoice")
    commit(billing, wage, "distinct-wage")
    with billing.actor("maker") as (connection, repository, actor):
        assert repository.evidence(wage["id"], actor=actor)["payrun"]["amount_minor"] == 2501
        for table, owner_key, owner_id in (("hc_claim_heads", "payrun_id", wage["id"]), ("pb_claim_heads", "invoice_id", invoice["id"])):
            rows = connection.execute(sql.SQL("SELECT time_id,{},state FROM {} WHERE tenant_id=%s ORDER BY time_id").format(
                sql.Identifier(owner_key), sql.Identifier("reconforge", table)), (billing.base.tenant,)).fetchall()
            assert len(rows) == len(times) and {row["time_id"] for row in rows} == set(times)
            assert all(row[owner_key] == owner_id and row["state"] == "Consumed" for row in rows)
        current_budget = PostgresBudgetControlRepository(connection, billing.base.tenant).get(BudgetScope("work", "org", "entity"), budget["id"])
        with pytest.raises(FinancePostingError) as refused, connection.transaction():
            repository.prepare_payrun(SCOPE, time_ids=times, budget_id=budget["id"], expected_budget_version=current_budget["row_version"],
                period_id="period", posting_date="2026-10-04", journal_code="STOCK", expense_account_code="LABOR",
                liability_account_code="WAGES", cash_account_code="CASH", command_id="duplicate-wages", actor=actor)
        assert refused.value.code == "people_time_claim_conflict"
    for key, amount in (("distinct-partial", 1000), ("distinct-final", 5236)):
        post(billing, collection(billing, invoice, amount, key), key)
    proof = independently_verify(evidence(billing, invoice))
    assert proof["amount_minor"] == proof["collected_minor"] == 6236
    with billing.actor("maker", private=False) as (connection, _, _):
        balances = connection.execute("""SELECT a.account_code,sum(l.debit_minor-l.credit_minor) AS amount
            FROM reconforge.finance_entry_lines l JOIN reconforge.finance_posting_effects effect
            ON effect.tenant_id=l.tenant_id AND effect.entry_id=l.entry_id JOIN reconforge.finance_accounts a
            ON a.tenant_id=l.tenant_id AND a.id=l.account_id WHERE l.tenant_id=%s GROUP BY a.account_code""", (billing.base.tenant,)).fetchall()
        assert {row["account_code"]: int(row["amount"]) for row in balances} == {"AR": 0, "REVENUE": -6236, "CASH": 6236, "LABOR": 2501, "WAGES": -2501}
    with pytest.raises(FinancePostingError):
        prepare(billing, times, prices, "duplicate-billing")
