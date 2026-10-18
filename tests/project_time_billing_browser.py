"""Synthetic approved-time input and read-only native PB1 browser evidence.

This browser slice starts from the separately governed HCM approved-time
fixture. Customer prices, invoices and cash collections must come from Studio.
The input fixture is not a new browser proof of employee/time creation.
"""

import hashlib
import importlib.util
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_project_time_billing import PostgresProjectTimeBillingRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from tests.people_project_payroll_browser import (
    personnel_browser_dsn,
    private_runtime,
    seed_people_project_payroll_browser,
)
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_people_project_payroll import approved_time

PROJECT_TIME_BILLING_TABLES = (
    "pb_prices", "pb_plans", "pb_commands", "pb_time_claims", "pb_claim_events", "pb_claim_heads", "pb_account_pins",
    "hc_times", "hc_projects", "ar_invoices", "ar_invoice_lines", "ar_receipts", "ar_receipt_allocations",
    "finance_entries", "finance_entry_lines", "finance_entry_line_dimensions", "finance_posting_effects",
    "domain_audit_events", "outbox_events",
)
PROJECT_TIME_BILLING_WORKSPACE_PROBE_TABLES = (
    "pb_prices", "pb_plans", "pb_commands", "pb_time_claims", "pb_claim_events", "pb_claim_heads", "pb_account_pins",
)
PROJECT_TIME_BILLING_TAMPER = (
    "UPDATE reconforge.ar_invoices SET pb_owner_id=NULL WHERE tenant_id=%s AND pb_owner_id IS NOT NULL",
    "DELETE FROM reconforge.pb_time_claims WHERE tenant_id=%s",
    "UPDATE reconforge.pb_plans SET amount_minor=amount_minor+1 WHERE tenant_id=%s",
)
PERMISSIONS = {"project_time_billing." + action for action in ("read", "manage", "approve_price", "prepare", "collect", "review", "post")}
PERMISSIONS |= {"receivables.read", "receivables.manage", "receivables.approve", "receivables.receive"}


def seed_project_time_billing_browser(admin_dsn: str, app_dsn: str) -> ReceiptRuntime:
    base = seed_people_project_payroll_browser(admin_dsn, app_dsn)
    with PostgresTenantBoundary(base.factory).transaction(base.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        for permission in sorted(PERMISSIONS):
            identity.create_permission(tenant_id=base.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=base.tenant, role_name="receipt-operator", permission_name=permission)
        finance = PostgresFinanceCoreRepository(connection, base.tenant)
        for code, kind in (("AR", "Asset"), ("REVENUE", "Income")):
            finance.upsert_account(account_code=code, name=code, account_type=kind, chart_code="DEFAULT", workspace="work")
        PostgresReceivablesRepository(connection, base.tenant).upsert_customer(customer_code="CUSTOMER", name="Synthetic project client",
            currency_code="USD", credit_limit_minor=100000, workspace="work", organization_code="ORG", entity_code="ENTITY")
    approved_time(private_runtime(base))
    return base


@contextmanager
def project_time_billing_restore_tamper_actor(base: ReceiptRuntime) -> Iterator[tuple[Any, Any, Any]]:
    with private_runtime(base).actor("poster", private=False) as (connection, _, actor):
        yield connection, PostgresProjectTimeBillingRepository(connection, base.tenant), actor


def verify_project_time_billing_browser(base: ReceiptRuntime) -> dict[str, Any]:
    from psycopg import sql

    with private_runtime(base).actor("maker", private=False) as (connection, _, actor):
        if connection.execute("SELECT pg_has_role(session_user,'reconforge_personnel_runtime','MEMBER') AS member").fetchone()["member"] is not False:
            raise ValueError("Ordinary billing login must not have personnel membership")
        rows = connection.execute("SELECT id FROM reconforge.pb_plans WHERE tenant_id=%s AND kind='Invoice' AND phase=2", (base.tenant,)).fetchall()
        if len(rows) != 1:
            raise ValueError("Browser must post exactly one original invoice")
        proof = PostgresProjectTimeBillingRepository(connection, base.tenant).evidence(rows[0]["id"], actor=actor)
        if proof["invoice"]["amount_minor"] != 6236 or len(proof["native_effects"]) != 3 or proof["ar_invoice"]["outstanding_minor"] != 0:
            raise ValueError("Browser original AR/native financial population differs")
        if proof["observed_native_balances"] != {"AR": "0", "REVENUE": "-6236", "CASH": "6236"}:
            raise ValueError("Browser source-only native balance differs")
        for table in ("hc_employee_private", "hc_rates", "hc_payrun_private", "hc_payment_private"):
            # Closed internal names; no credentials/private row contents leave this helper.
            if connection.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier("reconforge", table))).fetchone()["n"] != 0:
                raise ValueError("Ordinary billing evidence exposed private personnel data")
    def dates_only(value: Any) -> str:
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        raise TypeError("Only original date/timestamp values have explicit JSON conversion")
    raw = json.dumps(proof, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=dates_only).encode()
    proof = json.loads(raw)
    path = Path(__file__).resolve().parents[1] / ".github/scripts/verify_project_time_billing_cycle_oracle.py"
    spec = importlib.util.spec_from_file_location("project_billing_browser_independent_oracle", path)
    if spec is None or spec.loader is None:
        raise ValueError("The original independent oracle is unavailable")
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
    independent = oracle.verify(proof)
    if independent["amount_minor"] != 6236 or independent["collected_minor"] != 6236 or independent["native_effects"] != 3:
        raise ValueError("Independent original Project-minute/AR/GL conservation differs")
    return {"schema_version": "project-billing-browser-original-v1", "original_evidence": proof,
            "independent_oracle": independent, "original_evidence_canonical_sha256": hashlib.sha256(raw).hexdigest(),
            "oracle_source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "starting_input": "existing_hcm_approved_time_fixture", "employee_time_browser_creation_proven": False,
            "country_tax_packs": 0, "bank_execution_proven": False, "performance_comparison_accepted": False}


__all__ = ["PROJECT_TIME_BILLING_TABLES", "PROJECT_TIME_BILLING_WORKSPACE_PROBE_TABLES", "PROJECT_TIME_BILLING_TAMPER",
           "personnel_browser_dsn", "seed_project_time_billing_browser", "verify_project_time_billing_browser", "project_time_billing_restore_tamper_actor"]
