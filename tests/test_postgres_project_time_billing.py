"""Actual native development cycle over HC time, existing AR and existing GL."""

from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.project_time_billing import ProjectPriceAgreement
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_project_time_billing import PostgresProjectTimeBillingRepository
from reconforge.infrastructure.postgres_project_time_billing_schema import (
    downgrade_project_time_billing_schema,
    upgrade_project_time_billing_schema,
)
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from reconforge.platform.receivables import ReceiptAllocationInput, ReceivableInvoiceLineInput
from tests.test_postgres_people_project_payroll import (  # noqa: F401
    SCOPE,
    PeopleRuntime,
    approved_time,
    people,
    personnel_database,
    receipt_database,
)


@pytest.fixture
def billing(people: PeopleRuntime, personnel_database: tuple[str, str, str]) -> PeopleRuntime:  # noqa: F811
    import psycopg
    from psycopg import sql

    with psycopg.connect(personnel_database[0]) as admin:
        if admin.execute("SELECT to_regclass('reconforge.pb_plans')").fetchone()[0] is None:
            upgrade_project_time_billing_schema(admin)
        for dsn in personnel_database[1:]:
            login = psycopg.conninfo.conninfo_to_dict(dsn)["user"]
            admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(sql.Identifier(login)))
    with PostgresTenantBoundary(people.base.factory).transaction(people.base.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        permissions = {"project_time_billing." + name for name in ("read", "manage", "approve_price", "prepare", "collect", "review", "post")}
        permissions |= {"receivables.read", "receivables.manage", "receivables.approve", "receivables.receive"}
        for permission in sorted(permissions):
            identity.create_permission(tenant_id=people.base.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=people.base.tenant, role_name="receipt-operator", permission_name=permission)
        finance = PostgresProjectTimeBillingRepository(connection, people.base.tenant).owner.finance
        finance.upsert_account(account_code="AR", name="Project AR", account_type="Asset", chart_code="DEFAULT", workspace="work")
        finance.upsert_account(account_code="REVENUE", name="Project revenue", account_type="Income", chart_code="DEFAULT", workspace="work")
        PostgresReceivablesRepository(connection, people.base.tenant).upsert_customer(customer_code="CUSTOMER", name="Synthetic project client",
            currency_code="USD", credit_limit_minor=100000, workspace="work", organization_code="ORG", entity_code="ENTITY")
    return people


def sources(runtime: PeopleRuntime) -> tuple[list[str], list[str]]:
    times = approved_time(runtime)
    with runtime.actor("maker", private=False) as (connection, _, actor):
        repository = PostgresProjectTimeBillingRepository(connection, runtime.base.tenant)
        projects = connection.execute("SELECT id,project_code FROM reconforge.hc_projects WHERE tenant_id=%s ORDER BY project_code", (runtime.base.tenant,)).fetchall()
        prices = [repository.register_price(ProjectPriceAgreement(SCOPE, "CUSTOMER", project["id"], "2026-10-01", "2026-10-31", "USD", 2001 if project["project_code"] == "P1" else 3001, "Synthetic price"), command_id="price-"+project["project_code"], actor=actor) for project in projects]
    with runtime.actor("checker", private=False) as (connection, _, actor):
        repository = PostgresProjectTimeBillingRepository(connection, runtime.base.tenant)
        for price in prices:
            repository.approve_price(price["id"], expected_digest=price["source_digest"], command_id="price-approve-"+price["id"], actor=actor)
    return times, [price["id"] for price in prices]


def prepare(runtime: PeopleRuntime, times: list[str], prices: list[str], command: str = "prepare") -> dict[str, Any]:
    with runtime.actor("maker", private=False) as (connection, _, actor):
        return PostgresProjectTimeBillingRepository(connection, runtime.base.tenant).prepare_invoice(SCOPE, time_ids=times, price_ids=prices,
            customer_code="CUSTOMER", invoice_number="BILL-"+command.upper(), period_id="period", posting_date="2026-10-04", due_date="2026-10-15",
            journal_code="STOCK", receivable_account_code="AR", revenue_account_code="REVENUE", cash_account_code="CASH", command_id=command, actor=actor)


def post(runtime: PeopleRuntime, plan: dict[str, Any], suffix: str) -> dict[str, Any]:
    with runtime.actor("checker", private=False) as (connection, _, actor):
        PostgresProjectTimeBillingRepository(connection, runtime.base.tenant).review(plan["id"], expected_plan_digest=plan["plan_digest"], command_id="review-"+suffix, actor=actor)
    with runtime.actor("poster", private=False) as (connection, _, actor):
        return PostgresProjectTimeBillingRepository(connection, runtime.base.tenant).post(plan["id"], expected_plan_digest=plan["plan_digest"], command_id="post-"+suffix, actor=actor)


def test_empty_owned_schema_roundtrip_preserves_native_ar_and_exact_force_rls_catalog(receipt_database: tuple[str, str]) -> None:  # noqa: F811
    import psycopg
    with psycopg.connect(receipt_database[0]) as admin:
        if admin.execute("SELECT to_regclass('reconforge.pb_plans')").fetchone()[0] is None:
            upgrade_project_time_billing_schema(admin)
        expected = {"pb_prices", "pb_plans", "pb_commands", "pb_time_claims", "pb_claim_events", "pb_claim_heads", "pb_account_pins"}
        def catalog() -> list[tuple[Any, ...]]:
            return admin.execute("SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='reconforge' AND c.relname=ANY(%s) ORDER BY c.relname", (list(expected),)).fetchall()
        before = catalog()
        assert {row[0] for row in before} == expected and all(row[1] is True and row[2] is True for row in before)
        assert admin.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='reconforge' AND p.proname LIKE 'pb_%' AND(prosecdef OR proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog'])").fetchone()[0] == 0
        native_before = admin.execute("SELECT count(*) FROM reconforge.ar_customers ", ()).fetchone()[0]
        downgrade_project_time_billing_schema(admin)
        assert not catalog()
        assert admin.execute("SELECT count(*) FROM reconforge.ar_customers ", ()).fetchone()[0] == native_before
        upgrade_project_time_billing_schema(admin)
        assert catalog() == before


def test_actual_whole_approved_time_native_ar_project_revenue_partial_and_final_cash(billing: PeopleRuntime) -> None:
    import json
    import os
    from datetime import date, datetime
    from pathlib import Path

    times, prices = sources(billing)
    plan = prepare(billing, times, prices)
    assert plan["amount_minor"] == 6236
    with billing.actor("maker", private=False) as (connection, _, _):
        assert PostgresReceivablesRepository(connection, billing.base.tenant).get_invoice(plan["ar_invoice_id"])["status"] == "Submitted"
    post(billing, plan, "invoice")
    for suffix, amount in (("partial", 1000), ("final", 5236)):
        with billing.actor("maker", private=False) as (connection, _, actor):
            collection = PostgresProjectTimeBillingRepository(connection, billing.base.tenant).prepare_collection(plan["id"], amount_minor=amount,
                period_id="period", posting_date="2026-10-05", command_id="collect-"+suffix, actor=actor)
        post(billing, collection, suffix)
    with billing.actor("maker", private=False) as (connection, _, actor):
        proof = PostgresProjectTimeBillingRepository(connection, billing.base.tenant).evidence(plan["id"], actor=actor)
        assert len(proof["native_effects"]) == 3 and proof["ar_invoice"]["status"] == "Paid"
        assert proof["ar_invoice"]["outstanding_minor"] == 0
        balances = connection.execute("SELECT a.account_code,sum(l.debit_minor-l.credit_minor) balance FROM reconforge.finance_entry_lines l JOIN reconforge.finance_posting_effects e ON e.tenant_id=l.tenant_id AND e.entry_id=l.entry_id JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id WHERE l.tenant_id=%s GROUP BY a.account_code", (billing.base.tenant,)).fetchall()
        assert {row["account_code"]: int(row["balance"]) for row in balances} == {"AR": 0, "REVENUE": -6236, "CASH": 6236}
        assert proof["observed_native_balances"] == {row["account_code"]: str(int(row["balance"])) for row in balances}
        target = os.environ.get("RECONFORGE_PB1_EVIDENCE_DIRECTORY")
        if target:
            directory = Path(target)
            directory.mkdir(parents=True, exist_ok=True)
            def temporal(value: Any) -> str:
                if not isinstance(value, (date, datetime)):
                    raise TypeError("Evidence values must have an explicit JSON or date representation")
                return value.isoformat()
            with (directory / (plan["id"] + ".json")).open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(proof, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=temporal) + "\n")


def test_unposted_cancel_releases_billing_claim_history_then_reclaims_without_reusing_posted_time(billing: PeopleRuntime) -> None:
    times, prices = sources(billing)
    original = prepare(billing, times, prices)
    with billing.actor("maker", private=False) as (connection, _, actor):
        repository = PostgresProjectTimeBillingRepository(connection, billing.base.tenant)
        cancelled = repository.cancel(original["id"], expected_plan_digest=original["plan_digest"], command_id="cancel", actor=actor)
        assert cancelled["phase"] == 3
    replacement = prepare(billing, times, prices, "replacement")
    post(billing, replacement, "replacement")
    with pytest.raises(FinancePostingError):
        prepare(billing, times, prices, "double")


@pytest.mark.parametrize("tamper", ["ar_approval", "ar_collection", "owner_detach", "native_rename", "marker_forgery"])
def test_sql_cannot_detach_publish_or_forge_original_ar_and_native_owner(billing: PeopleRuntime, tamper: str) -> None:
    from uuid import uuid4
    times, prices = sources(billing)
    plan = prepare(billing, times, prices)
    if tamper == "ar_collection":
        post(billing, plan, "original")
    with pytest.raises(Exception) as refused, billing.actor("poster", private=False) as (connection, _, actor):
        ar = PostgresReceivablesRepository(connection, billing.base.tenant)
        if tamper == "ar_approval":
            invoice = ar.get_invoice(plan["ar_invoice_id"])
            ar.approve_invoice(invoice["id"], expected_version=invoice["row_version"], actor_label=actor.username)
        elif tamper == "ar_collection":
            ar.post_receipt(receipt_number="DETACHED", customer_code="CUSTOMER", receipt_date="2026-10-05", currency_code="USD", amount_minor=100,
                allocations=[ReceiptAllocationInput(plan["ar_invoice_id"], 100)], workspace="work", organization_code="ORG", entity_code="ENTITY", actor_label=actor.username)
        elif tamper == "owner_detach":
            connection.execute("UPDATE reconforge.ar_invoices SET pb_owner_id=NULL WHERE tenant_id=%s AND id=%s", (billing.base.tenant, plan["ar_invoice_id"]))
        elif tamper == "native_rename":
            connection.execute("UPDATE reconforge.finance_entries SET entry_number='DETACHED' WHERE tenant_id=%s AND id=%s", (billing.base.tenant, plan["entry_id"]))
        else:
            connection.execute("SELECT set_config('app.pb_invoice_source',%s,true)", ("PB1-"+uuid4().hex,))
            ar.create_invoice(invoice_number="FORGED", customer_code="CUSTOMER", invoice_date="2026-10-04", currency_code="USD", tax_minor=0,
                lines=[ReceivableInvoiceLineInput("Synthetic", "1", 100, 100)], workspace="work", organization_code="ORG", entity_code="ENTITY", actor_label=actor.username)
    assert getattr(refused.value, "sqlstate", None) in {"23503", "23514"} or isinstance(refused.value, FinancePostingError)
    with billing.actor("maker", private=False) as (connection, _, actor):
        proof = PostgresProjectTimeBillingRepository(connection, billing.base.tenant).evidence(plan["id"], actor=actor)
        assert len(proof["native_effects"]) == int(tamper == "ar_collection")
        assert proof["ar_invoice"]["allocated_minor"] == 0


def test_original_command_replay_survives_response_loss_but_refuses_changed_actor_or_request(billing: PeopleRuntime) -> None:
    times, prices = sources(billing)
    plan = prepare(billing, times, prices)
    assert prepare(billing, times, prices) == plan
    posted = post(billing, plan, "invoice")
    with billing.actor("poster", private=False) as (connection, _, actor):
        repository = PostgresProjectTimeBillingRepository(connection, billing.base.tenant)
        assert repository.post(plan["id"], expected_plan_digest=plan["plan_digest"], command_id="post-invoice", actor=actor) == posted
    with billing.actor("checker", private=False) as (connection, _, actor), pytest.raises(FinancePostingError):
        PostgresProjectTimeBillingRepository(connection, billing.base.tenant).post(plan["id"], expected_plan_digest=plan["plan_digest"], command_id="post-invoice", actor=actor)


def test_legacy_ar_and_finance_work_without_any_pb_table_acl(billing: PeopleRuntime, personnel_database: tuple[str, str, str]) -> None:  # noqa: F811
    import psycopg
    from psycopg import sql
    ordinary = psycopg.conninfo.conninfo_to_dict(personnel_database[1])["user"]
    tables = ["pb_prices", "pb_plans", "pb_commands", "pb_time_claims", "pb_claim_events", "pb_claim_heads", "pb_account_pins"]
    with psycopg.connect(personnel_database[0]) as admin:
        for table in tables:
            admin.execute(sql.SQL("REVOKE ALL ON reconforge.{} FROM {}").format(sql.Identifier(table), sql.Identifier(ordinary)))
    try:
        with billing.actor("maker", private=False) as (connection, _, actor):
            ar = PostgresReceivablesRepository(connection, billing.base.tenant)
            invoice = ar.create_invoice(invoice_number="LEGACY", customer_code="CUSTOMER", invoice_date="2026-10-04", currency_code="USD", tax_minor=0,
                lines=[ReceivableInvoiceLineInput("Legacy service", "1", 100, 100)], workspace="work", organization_code="ORG", entity_code="ENTITY", actor_label=actor.username)
            ar.submit_invoice(invoice["id"], expected_version=invoice["row_version"], actor_label=actor.username)
            entry = PostgresProjectTimeBillingRepository(connection, billing.base.tenant).owner.finance.create_entry(entry_number="LEGACY",
                organization_code="ORG", entity_code="ENTITY", period_id="period", journal_code="STOCK", posting_date="2026-10-04", description="Ordinary native ledger",
                workspace="work", lines=[{"account_code":"AR","debit":"1","credit":"0"},{"account_code":"REVENUE","debit":"0","credit":"1"}], actor_label=actor.username)
        with billing.actor("checker", private=False) as (connection, _, actor):
            ar = PostgresReceivablesRepository(connection, billing.base.tenant)
            invoice = ar.get_invoice(invoice["id"])
            ar.approve_invoice(invoice["id"], expected_version=invoice["row_version"], actor_label=actor.username)
            PostgresProjectTimeBillingRepository(connection, billing.base.tenant).owner.finance.validate_entry(entry["id"], reason="Legacy review", actor_label=actor.username)
        with billing.actor("poster", private=False) as (connection, _, actor):
            owner = PostgresProjectTimeBillingRepository(connection, billing.base.tenant).owner
            snapshot = PostgresProjectTimeBillingRepository(connection, billing.base.tenant)._snapshot(entry["id"])
            from reconforge.domain.finance_posting import validation_digest
            effect = owner.posting.post(entry["id"], command_id="legacy-post", expected_validation_digest=validation_digest(snapshot), reason="Legacy source", actor=actor)
            assert effect["entry_id"] == entry["id"]
            PostgresReceivablesRepository(connection, billing.base.tenant).post_receipt(receipt_number="LEGACY", customer_code="CUSTOMER",
                receipt_date="2026-10-05", currency_code="USD", amount_minor=100, allocations=[ReceiptAllocationInput(invoice["id"],100)],
                workspace="work", organization_code="ORG", entity_code="ENTITY", actor_label=actor.username)
    finally:
        with psycopg.connect(personnel_database[0]) as admin:
            for table in tables:
                admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{} TO {}").format(sql.Identifier(table), sql.Identifier(ordinary)))


def test_native_credit_guard_refuses_direct_ar_approval_bypass_before_atomic_publication(billing: PeopleRuntime, monkeypatch) -> None:
    times, prices = sources(billing)
    plan = prepare(billing, times, prices)
    with billing.actor("checker", private=False) as (connection, _, actor):
        PostgresProjectTimeBillingRepository(connection, billing.base.tenant).review(plan["id"], expected_plan_digest=plan["plan_digest"], command_id="review", actor=actor)
    with billing.actor("maker", private=False) as (connection, _, _):
        connection.execute("UPDATE reconforge.ar_customers SET credit_hold=TRUE WHERE tenant_id=%s AND customer_code='CUSTOMER'", (billing.base.tenant,))
    with billing.actor("poster", private=False) as (connection, _, actor):
        repository = PostgresProjectTimeBillingRepository(connection, billing.base.tenant)
        def direct_approval(invoice_id: str, **kwargs) -> dict[str, Any]:
            connection.execute("UPDATE reconforge.ar_invoices SET status='Approved',approved_by=%s,approved_at=now(),row_version=row_version+1 WHERE tenant_id=%s AND id=%s", (actor.username, billing.base.tenant, invoice_id))
            return repository.ar.get_invoice(invoice_id)
        monkeypatch.setattr(repository.ar, "approve_invoice", direct_approval)
        with pytest.raises(FinancePostingError) as refused:
            repository.post(plan["id"], expected_plan_digest=plan["plan_digest"], command_id="post", actor=actor)
        assert getattr(refused.value.__cause__, "diag", None).constraint_name == "project_billing_owner"
    with billing.actor("maker", private=False) as (connection, _, actor):
        proof = PostgresProjectTimeBillingRepository(connection, billing.base.tenant).evidence(plan["id"], actor=actor)
        assert proof["native_effects"] == [] and proof["ar_invoice"]["status"] == "Submitted"


def test_concurrent_whole_time_claims_have_one_native_invoice_and_no_double_revenue(billing: PeopleRuntime) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    times, prices = sources(billing)
    barrier = Barrier(2)
    def attempt(index: int) -> dict[str, Any] | None:
        barrier.wait(timeout=10)
        try:
            return prepare(billing, times, prices, "race-"+str(index))
        except FinancePostingError:
            return None
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(attempt, (1, 2)))
    winners = [value for value in results if value is not None]
    assert len(winners) == 1
    post(billing, winners[0], "race-winner")
    with billing.actor("maker", private=False) as (connection, _, actor):
        proof = PostgresProjectTimeBillingRepository(connection, billing.base.tenant).evidence(winners[0]["id"], actor=actor)
        assert len(proof["native_effects"]) == 1
        assert connection.execute("SELECT count(*) FROM reconforge.pb_plans WHERE tenant_id=%s AND kind='Invoice'", (billing.base.tenant,)).fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM reconforge.ar_invoices WHERE tenant_id=%s", (billing.base.tenant,)).fetchone()[0] == 1


@pytest.mark.parametrize("read", ["get", "catalog", "evidence"])
def test_original_financial_read_supplies_payload_precision_and_amount_to_central_policy(billing: PeopleRuntime,
        read: str, monkeypatch) -> None:
    from decimal import Decimal

    import reconforge.infrastructure.postgres_operational_finance as native_owner
    from reconforge.auth.policy import evaluate_principal_access
    times, prices = sources(billing)
    plan = prepare(billing, times, prices)
    observed = []
    def bounded(principal, **context):
        amount = context.get("amount")
        if context["required_permission"] == "project_time_billing.read" and amount is not None:
            observed.append(amount)
            return evaluate_principal_access(principal, maximum_amount=Decimal("20.00"), **context)
        return evaluate_principal_access(principal, **context)
    monkeypatch.setattr(native_owner, "evaluate_principal_access", bounded)
    with billing.actor("maker", private=False) as (connection, _, actor), pytest.raises(FinancePostingError) as refused:
        repository = PostgresProjectTimeBillingRepository(connection, billing.base.tenant)
        if read == "catalog":
            repository.catalog(SCOPE, actor=actor)
        else:
            getattr(repository, read)(plan["id"], actor=actor)
    assert "denied" in refused.value.code and observed == [Decimal("62.36")]


@pytest.mark.parametrize("read", ["get", "catalog", "evidence"])
@pytest.mark.parametrize("revoked", ["scope", "permission"])
def test_cached_human_billing_read_refuses_current_persisted_authority_revocation(billing: PeopleRuntime,
        read: str, revoked: str) -> None:
    import psycopg

    from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
    times, prices = sources(billing)
    plan = prepare(billing, times, prices)
    with billing.actor("maker", private=False) as (connection, _, actor):
        with psycopg.connect(billing.base.admin_dsn) as admin:
            if revoked == "scope":
                PostgresScopeAuthorityRepository(admin).revoke(tenant_id=billing.base.tenant,
                    grant_id="hc-makerlegal_entity", actor_id="poster", reason="Synthetic billing read authority revocation")
            else:
                admin.execute("UPDATE reconforge.identity_role_permissions SET active=FALSE,lifecycle_version=lifecycle_version+1,revoked_at=now(),revoked_by='poster',revocation_reason_code='access_change' WHERE tenant_id=%s AND permission_name='project_time_billing.read'", (billing.base.tenant,))
        with pytest.raises(FinancePostingError) as refused:
            repository = PostgresProjectTimeBillingRepository(connection, billing.base.tenant)
            if read == "catalog":
                repository.catalog(SCOPE, actor=actor)
            else:
                getattr(repository, read)(plan["id"], actor=actor)
        assert "denied" in refused.value.code


@pytest.mark.parametrize("permission", ["finance_core.read", "people_project_payroll.read", "receivables.read"])
def test_unposted_evidence_applies_separate_financial_read_ceiling_with_module_read_allowed(billing: PeopleRuntime,
        permission: str, monkeypatch) -> None:
    from decimal import Decimal

    import reconforge.infrastructure.postgres_operational_finance as native_owner
    from reconforge.auth.policy import evaluate_principal_access
    times, prices = sources(billing)
    plan = prepare(billing, times, prices)
    observed = []
    def bounded(principal, **context):
        amount = context.get("amount")
        if context["required_permission"] == permission and amount is not None:
            observed.append(amount)
            return evaluate_principal_access(principal, maximum_amount=Decimal("20.00"), **context)
        return evaluate_principal_access(principal, **context)
    monkeypatch.setattr(native_owner, "evaluate_principal_access", bounded)
    with billing.actor("maker", private=False) as (connection, _, actor), pytest.raises(FinancePostingError) as refused:
        PostgresProjectTimeBillingRepository(connection, billing.base.tenant).evidence(plan["id"], actor=actor)
    assert "denied" in refused.value.code and observed == [Decimal("62.36")]
