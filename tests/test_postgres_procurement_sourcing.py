"""Restricted-role native sourcing-to-budget/stock/AP/GL with direct SQL closure."""
from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from reconforge.domain.budget_control import BudgetControlError, BudgetScope
from reconforge.domain.procurement_partial import ProcurementPartialError
from reconforge.domain.procurement_sourcing import PERMISSIONS, RequisitionPreparation, SupplierQuotationPreparation
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_payables import PostgresPayablesRepository
from reconforge.infrastructure.postgres_procurement_sourcing import PostgresProcurementSourcingRepository
from reconforge.infrastructure.postgres_procurement_sourcing_schema import install_postgres_procurement_sourcing
from tests.test_postgres_procurement_commitments import budget_runtime as base_budget_runtime
from tests.test_postgres_procurement_commitments import receipt_database as base_receipt_database
from tests.test_postgres_procurement_multiline import (
    action,
    enterprise_digest,
    invoice_lines,
    pay_invoice,
    receive_line,
)
from tests.test_postgres_procurement_partial import CHECKER, MAKER, POSTER
from tests.test_procurement_multiline import enterprise_request

TABLES = ("procurement_sourcing_requisitions", "procurement_sourcing_quotes", "procurement_sourcing_events", "procurement_sourcing_commands")


@pytest.fixture(scope="module")
def receipt_database() -> Iterator[tuple[str, str]]:
    import psycopg
    from psycopg import sql
    delegated = base_receipt_database.__wrapped__()
    try:
        database = next(delegated)
        with psycopg.connect(database[0]) as admin:
            install_postgres_procurement_sourcing(admin)
            app_user = psycopg.conninfo.conninfo_to_dict(database[1])["user"]
            for table in TABLES:
                admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{} TO {}").format(sql.Identifier(table), sql.Identifier(app_user)))
        yield database
    finally:
        delegated.close()


@pytest.fixture
def sourcing_runtime(receipt_database: tuple[str, str]) -> tuple[Any, dict[str, Any]]:
    runtime, budget = base_budget_runtime.__wrapped__(receipt_database)
    with runtime.actor(MAKER) as (connection, _, _):
        identities = PostgresIdentityRepository(connection)
        for permission in sorted(set().union(*PERMISSIONS.values())):
            identities.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identities.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
        PostgresPayablesRepository(connection, runtime.tenant).upsert_supplier(supplier_code="ALT", name="Synthetic competing supplier",
            currency_code="USD", workspace="work", organization_code="ORG", entity_code="ENTITY")
        assert tuple(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == (False, False)
    return runtime, budget


def requisition(runtime: Any, budget: dict[str, Any], number: str = "SRC5-1") -> dict[str, Any]:
    with runtime.actor(MAKER) as (connection, _, actor):
        repository = PostgresProcurementSourcingRepository(connection, runtime.tenant)
        request = RequisitionPreparation(budget_id=budget["id"], order=enterprise_request(number), reason="Actual source-owned mixed-unit demand")
        result = repository.create(request, command_id="source-create", actor=actor)
        assert repository.create(request, command_id="source-create", actor=actor) == result
        return result


def stage(runtime: Any, head: dict[str, Any], operation: str, name: str, **fields: Any) -> dict[str, Any]:
    with runtime.actor(name) as (connection, _, actor):
        repository = PostgresProcurementSourcingRepository(connection, runtime.tenant)
        args = {"expected_version": head["row_version"], "command_id": "source-" + operation,
                "reason": "Independent exact supplier selection and appropriation", "actor": actor, **fields}
        result = repository.act(head["id"], operation, **args)
        assert repository.act(head["id"], operation, **args) == result
        return result


def quoted(runtime: Any, budget: dict[str, Any]) -> dict[str, Any]:
    head = stage(runtime, requisition(runtime, budget), "open-rfq", CHECKER)
    for supplier, prices in (("ALT", (1300, 2000)), ("SUP", (1200, 2000))):
        with runtime.actor(MAKER) as (connection, _, actor):
            repository = PostgresProcurementSourcingRepository(connection, runtime.tenant)
            args = {"expected_version": head["row_version"], "command_id": "quote-" + supplier, "actor": actor}
            request = SupplierQuotationPreparation(supplier_code=supplier, unit_prices_minor=prices, valid_until="2026-10-31",
                reason="Retained supplier original commercial offer")
            head = repository.record_quotation(head["id"], request, **args)
            assert repository.record_quotation(head["id"], request, **args) == head
    return head


def source_digest(runtime: Any) -> str:
    from psycopg import sql

    from reconforge.domain.finance_posting import digest_payload
    with runtime.actor(MAKER) as (connection, _, _):
        source = {"native": enterprise_digest(connection, runtime.tenant)}
        for table in (*TABLES, "budget_envelopes", "budget_commitment_events", "budget_commands", "procurement_commitment_plans", "procurement_commitment_commands"):
            source[table] = [row["value"] for row in connection.execute(sql.SQL("SELECT to_jsonb(t) value FROM reconforge.{} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text")
                .format(sql.Identifier(table)), (runtime.tenant,)).fetchall()]
        return digest_payload(source)


def test_actual_sourcing_award_native_partial_receipts_ap_payments_and_budget_release(sourcing_runtime: tuple[Any, dict[str, Any]]) -> None:
    runtime, budget = sourcing_runtime
    head = quoted(runtime, budget)
    with runtime.actor(MAKER) as (connection, _, actor):
        detail = PostgresProcurementSourcingRepository(connection, runtime.tenant).get(head["id"], actor=actor)
        assert [quote["payload"]["total_minor"] for quote in detail["quotations"]] == ["17000", "18000"]
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
        assert connection.execute("SELECT count(*) n FROM reconforge.procurement_partial_orders WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
    head = stage(runtime, head, "review-selection", CHECKER)
    head = stage(runtime, head, "award", POSTER, expected_budget_version=budget["row_version"])
    with runtime.actor(POSTER) as (connection, _, actor):
        repository = PostgresProcurementSourcingRepository(connection, runtime.tenant)
        purchase = repository.purchase.get(head["order_id"], actor=actor)
        owner = repository.commitments.get(head["order_id"], actor=actor)
        assert purchase["order"]["number"] == "BPC1-SRC5-1" and owner["original_minor"] == "17000"
    purchase = action(runtime, action(runtime, purchase, "submit-order", POSTER), "approve-order", CHECKER)
    purchase = receive_line(runtime, purchase, 0, "2")
    purchase = receive_line(runtime, purchase, 1, "2.50")
    purchase = invoice_lines(runtime, purchase, ((0, "2"), (1, "2.50")))
    invoice = purchase["invoices"][-1]["id"]
    for operation, name in (("approve-invoice", CHECKER), ("prepare-accrual", MAKER), ("review-accrual", CHECKER)):
        purchase = action(runtime, purchase, operation, name, invoice)
    with runtime.actor(POSTER) as (connection, _, actor):
        repository = PostgresProcurementSourcingRepository(connection, runtime.tenant)
        owner = repository.commitments.consume_invoice(head["order_id"], invoice, expected_order_version=purchase["order"]["row_version"],
            expected_budget_version=owner["budget_version"], command_id="source-consume", reason="Same original AP and native budget effect", actor=actor)
        purchase = repository.purchase.get(head["order_id"], actor=actor)
    pay_invoice(runtime, purchase["invoices"][-1]["native_invoice_id"], 2400, "source-payment-one")
    pay_invoice(runtime, purchase["invoices"][-1]["native_invoice_id"], 5000, "source-payment-two")
    with runtime.actor(CHECKER) as (connection, _, actor):
        repository = PostgresProcurementSourcingRepository(connection, runtime.tenant)
        owner = repository.commitments.release(head["order_id"], expected_order_version=purchase["order"]["row_version"],
            expected_budget_version=owner["budget_version"], posting_date="2026-10-04", command_id="source-release",
            reason="Independent unreceived obligation release", actor=actor)
        envelope = repository.budgets.get(BudgetScope("work", "org", "entity"), budget["id"])
        assert (owner["consumed_minor"], owner["released_minor"], owner["remaining_minor"], envelope["available_minor"]) == ("7400", "9600", "0", "12600")
        assert tuple(connection.execute("SELECT sum(debit_minor),sum(credit_minor) FROM reconforge.finance_entry_lines WHERE tenant_id=%s", (runtime.tenant,)).fetchone()) == (22200, 22200)
        assert connection.execute("SELECT sum(remaining_value_minor) n FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 7400
        assert repository.get(head["id"], actor=actor)["head"]["status"] == "Awarded"


@pytest.mark.parametrize("operation,name", [("open-rfq", MAKER), ("review-selection", MAKER), ("award", MAKER), ("award", CHECKER)])
def test_same_human_approval_and_award_refuse_without_partial_effect(sourcing_runtime: tuple[Any, dict[str, Any]], operation: str, name: str) -> None:
    runtime, budget = sourcing_runtime
    head = requisition(runtime, budget) if operation == "open-rfq" else quoted(runtime, budget)
    if operation == "award":
        head = stage(runtime, head, "review-selection", CHECKER)
    before = source_digest(runtime)
    with pytest.raises(ProcurementPartialError, match="independent|reviewer"):
        stage(runtime, head, operation, name, **({"expected_budget_version": budget["row_version"]} if operation == "award" else {}))
    assert source_digest(runtime) == before


def test_fault_after_native_budget_purchase_rolls_back_award_and_all_participants(sourcing_runtime: tuple[Any, dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, budget = sourcing_runtime
    head = stage(runtime, quoted(runtime, budget), "review-selection", CHECKER)
    before = source_digest(runtime)
    with runtime.actor(POSTER) as (connection, _, actor):
        repository = PostgresProcurementSourcingRepository(connection, runtime.tenant)
        def fail(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("injected late source acknowledgment fault")
        monkeypatch.setattr(repository, "_remember", fail)
        with pytest.raises(RuntimeError, match="injected late"):
            repository.act(head["id"], "award", expected_version=head["row_version"], expected_budget_version=budget["row_version"],
                command_id="late-failed-award", reason="Atomic source and budget-backed purchase", actor=actor)
    assert source_digest(runtime) == before


@pytest.mark.parametrize("target", ["source", "quote", "event", "ack", "detached-phase"])
def test_direct_sql_cannot_rewrite_or_detach_retained_sourcing(sourcing_runtime: tuple[Any, dict[str, Any]], target: str) -> None:
    import psycopg
    runtime, budget = sourcing_runtime
    head = quoted(runtime, budget)
    before = source_digest(runtime)
    with runtime.actor(CHECKER) as (connection, _, actor), pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
        connection.execute("SELECT set_config('app.procurement_sourcing_actor_id',%s,true)", (actor.user_id,))
        if target == "source":
            connection.execute("UPDATE reconforge.procurement_sourcing_requisitions SET payload=payload||'{\"tampered\":true}'::jsonb WHERE tenant_id=%s", (runtime.tenant,))
        elif target == "quote":
            connection.execute("UPDATE reconforge.procurement_sourcing_quotes SET total_minor=1 WHERE tenant_id=%s", (runtime.tenant,))
        elif target == "event":
            connection.execute("DELETE FROM reconforge.procurement_sourcing_events WHERE tenant_id=%s", (runtime.tenant,))
        elif target == "ack":
            connection.execute("UPDATE reconforge.procurement_sourcing_commands SET response_json='{}'::jsonb WHERE tenant_id=%s", (runtime.tenant,))
        else:
            connection.execute("UPDATE reconforge.procurement_sourcing_requisitions SET phase=2,row_version=row_version+1 WHERE tenant_id=%s AND id=%s", (runtime.tenant, head["id"]))
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert source_digest(runtime) == before


def test_same_lost_award_response_concurrently_commits_one_native_purchase(sourcing_runtime: tuple[Any, dict[str, Any]]) -> None:
    runtime, budget = sourcing_runtime
    head = stage(runtime, quoted(runtime, budget), "review-selection", CHECKER)
    def attempt() -> dict[str, Any]:
        with runtime.actor(POSTER) as (connection, _, actor):
            return PostgresProcurementSourcingRepository(connection, runtime.tenant).act(head["id"], "award",
                expected_version=head["row_version"], expected_budget_version=budget["row_version"], command_id="same-source-award",
                reason="Concurrent exact original award", actor=actor)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = list(pool.map(lambda _: attempt(), range(2)))
    assert one == two and one["status"] == "Awarded"
    with runtime.actor(POSTER) as (connection, _, _):
        assert connection.execute("SELECT count(*) n FROM reconforge.procurement_partial_orders WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) n FROM reconforge.budget_commitment_events WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1


def test_original_lost_response_retry_rechecks_current_sourcing_permission(sourcing_runtime: tuple[Any, dict[str, Any]]) -> None:
    runtime, budget = sourcing_runtime
    head = requisition(runtime, budget)
    with runtime.actor(CHECKER) as (connection, _, _):
        connection.execute("UPDATE reconforge.identity_role_permissions SET active=FALSE,lifecycle_version=lifecycle_version+1,revoked_at=now(),revoked_by=%s,revocation_reason_code='access_change' WHERE tenant_id=%s AND permission_name='procurement_sourcing.manage'",
            ("id-" + CHECKER, runtime.tenant))
    with runtime.actor(MAKER) as (connection, _, actor), pytest.raises(BudgetControlError, match="authority"):
        PostgresProcurementSourcingRepository(connection, runtime.tenant).create(RequisitionPreparation(budget_id=budget["id"],
            order=enterprise_request("SRC5-1"), reason="Actual source-owned mixed-unit demand"), command_id="source-create", actor=actor)
    assert head["status"] == "Draft"


def test_cancelled_original_rfq_keeps_offer_evidence_without_native_po(sourcing_runtime: tuple[Any, dict[str, Any]]) -> None:
    runtime, budget = sourcing_runtime
    head = stage(runtime, quoted(runtime, budget), "cancel", CHECKER)
    with runtime.actor(MAKER) as (connection, _, actor):
        detail = PostgresProcurementSourcingRepository(connection, runtime.tenant).get(head["id"], actor=actor)
        assert detail["head"]["status"] == "Cancelled" and len(detail["quotations"]) == 2 and detail["head"]["order_id"] is None
        assert connection.execute("SELECT count(*) n FROM reconforge.budget_commitment_events WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0

def test_retained_offer_set_freezes_after_review_and_conflicting_command_cannot_rebind(sourcing_runtime: tuple[Any, dict[str, Any]]) -> None:
    runtime, budget = sourcing_runtime
    reviewed = stage(runtime, quoted(runtime, budget), "review-selection", CHECKER)
    before = source_digest(runtime)
    with runtime.actor(MAKER) as (connection, _, actor):
        repository = PostgresProcurementSourcingRepository(connection, runtime.tenant)
        with pytest.raises(ProcurementPartialError, match="opened RFQ"):
            repository.record_quotation(reviewed["id"], SupplierQuotationPreparation(supplier_code="SUP",
                unit_prices_minor=(1000, 1800), valid_until="2026-10-31", reason="Cannot replace frozen original offer"),
                expected_version=reviewed["row_version"], command_id="new-offer-after-selection", actor=actor)
        with pytest.raises(ProcurementPartialError, match="another exact"):
            repository.record_quotation(reviewed["id"], SupplierQuotationPreparation(supplier_code="ALT",
                unit_prices_minor=(1300, 2000), valid_until="2026-10-31", reason="Changed reason on retained key"),
                expected_version=2, command_id="quote-ALT", actor=actor)
    assert source_digest(runtime) == before


def test_ordinary_budget_purchase_cannot_bypass_reserved_sourcing_namespace(sourcing_runtime: tuple[Any, dict[str, Any]]) -> None:
    import psycopg

    from reconforge.domain.procurement_commitments import BudgetPurchasePreparation

    runtime, budget = sourcing_runtime
    before = source_digest(runtime)
    with pytest.raises(psycopg.errors.CheckViolation, match="exact original award owner"), runtime.actor(POSTER) as (connection, _, actor):
        PostgresProcurementSourcingRepository(connection, runtime.tenant).commitments.create(
            BudgetPurchasePreparation(budget_id=budget["id"], expected_budget_version=budget["row_version"],
                order=enterprise_request("BPC1-SRC5-ORPHAN"), reason="Cannot evade retained RFQ approval"),
            command_id="orphan-sourcing-po", actor=actor)
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert source_digest(runtime) == before


def test_native_sourcing_tables_force_scope_and_tenant_isolation(sourcing_runtime: tuple[Any, dict[str, Any]]) -> None:
    runtime, budget = sourcing_runtime
    head = quoted(runtime, budget)
    with runtime.actor(MAKER) as (connection, _, _):
        assert all(row["relrowsecurity"] and row["relforcerowsecurity"] for row in connection.execute(
            "SELECT relrowsecurity,relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='reconforge' AND relname=ANY(%s)", (list(TABLES),)).fetchall())
        connection.execute("SELECT set_config('app.legal_entity_id','foreign',true)")
        for table in TABLES:
            assert connection.execute("SELECT count(*) n FROM reconforge." + table + " WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
        connection.execute("SELECT set_config('app.legal_entity_id','entity',true)")
        connection.execute("SELECT set_config('app.tenant_id','foreign',true)")
        assert connection.execute("SELECT count(*) n FROM reconforge.procurement_sourcing_requisitions WHERE id=%s", (head["id"],)).fetchone()["n"] == 0


def test_populated_sourcing_migration_refuses_destructive_downgrade(sourcing_runtime: tuple[Any, dict[str, Any]]) -> None:
    import psycopg

    from reconforge.infrastructure.postgres_procurement_sourcing_schema import DOWNGRADE_SQL

    runtime, budget = sourcing_runtime
    requisition(runtime, budget)
    before = source_digest(runtime)
    with psycopg.connect(runtime.admin_dsn) as admin, pytest.raises(psycopg.errors.RaiseException, match="Retained sourcing history"), admin.transaction():
        admin.execute(DOWNGRADE_SQL)
    assert source_digest(runtime) == before


@pytest.mark.parametrize("candidate", ("retained", "proposed"))
def test_whole_offer_set_and_new_quote_obey_current_financial_cap(
    sourcing_runtime: tuple[Any, dict[str, Any]], monkeypatch: pytest.MonkeyPatch, candidate: str,
) -> None:
    from decimal import Decimal

    from reconforge.auth.policy import evaluate_principal_access
    from reconforge.infrastructure import budget_control_repository

    runtime, budget = sourcing_runtime
    head = quoted(runtime, budget) if candidate == "retained" else stage(runtime, requisition(runtime, budget), "open-rfq", CHECKER)
    before = source_digest(runtime)
    observed: list[Decimal] = []

    def bounded_policy(*args: Any, **kwargs: Any) -> Any:
        observed.append(kwargs["amount"])
        return evaluate_principal_access(*args, **kwargs, maximum_amount=Decimal("175.00"))

    monkeypatch.setattr(budget_control_repository, "evaluate_principal_access", bounded_policy)
    if candidate == "retained":
        # A 170.00 winning offer cannot authorize disclosure of a rejected 180.00 offer.
        for operation in ("read", "page", "create-replay", "quote-replay", "review", "cancel"):
            observed.clear()
            with runtime.actor(CHECKER if operation in {"review", "cancel"} else MAKER) as (connection, _, actor):
                repository = PostgresProcurementSourcingRepository(connection, runtime.tenant)
                with pytest.raises(BudgetControlError, match="current policy"):
                    if operation == "read":
                        repository.get(head["id"], actor=actor)
                    elif operation == "page":
                        repository.list_requisitions("work", actor=actor)
                    elif operation == "create-replay":
                        repository.create(RequisitionPreparation(budget_id=budget["id"], order=enterprise_request("SRC5-1"),
                            reason="Actual source-owned mixed-unit demand"), command_id="source-create", actor=actor)
                    elif operation == "quote-replay":
                        repository.record_quotation(head["id"], SupplierQuotationPreparation(supplier_code="ALT",
                            unit_prices_minor=(1300, 2000), valid_until="2026-10-31", reason="Retained supplier original commercial offer"),
                            expected_version=2, command_id="quote-ALT", actor=actor)
                    else:
                        repository.act(head["id"], "review-selection" if operation == "review" else "cancel",
                            expected_version=head["row_version"], command_id="cap-" + operation, reason="Cannot exceed retained evidence authority", actor=actor)
            assert observed[-1] == Decimal("180.00")
    else:
        with runtime.actor(MAKER) as (connection, _, actor):
            repository = PostgresProcurementSourcingRepository(connection, runtime.tenant)
            assert repository.get(head["id"], actor=actor)["head"] == head
            with pytest.raises(BudgetControlError, match="current policy"):
                repository.record_quotation(head["id"], SupplierQuotationPreparation(supplier_code="ALT",
                    unit_prices_minor=(1300, 2000), valid_until="2026-10-31", reason="A proposed offer also requires its full financial authority"),
                    expected_version=head["row_version"], command_id="cap-new-quote", actor=actor)
        assert observed[-1] == Decimal("180.00")
    assert source_digest(runtime) == before
