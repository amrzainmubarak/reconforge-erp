"""Native budget-backed purchase-to-pay and immutable released source evidence."""
from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
from typing import Any

import pytest

from reconforge.domain.budget_control import BudgetControlError, BudgetDefinition, BudgetScope, CommitmentAction
from reconforge.domain.finance_posting import digest_payload
from reconforge.domain.procurement_commitments import BudgetPurchasePreparation
from reconforge.domain.procurement_partial import PartialQuantityPreparation, ProcurementPartialError
from reconforge.infrastructure.postgres_budget_control import PostgresBudgetControlRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_procurement_commitments import PostgresProcurementCommitmentRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_procurement_multiline import (
    action,
    create_multiline_runtime,
    enterprise_digest,
    invoice_lines,
    pay_invoice,
    receive_line,
)
from tests.test_postgres_procurement_multiline import receipt_database as base_receipt_database
from tests.test_postgres_procurement_partial import CHECKER, MAKER, POSTER, pytestmark
from tests.test_procurement_multiline import enterprise_request

__all__ = ["pytestmark", "receipt_database"]
SCOPE = BudgetScope("work", "org", "entity")


@pytest.fixture(scope="module")
def receipt_database() -> Iterator[tuple[str, str]]:
    delegated = base_receipt_database.__wrapped__()
    try:
        yield next(delegated)
    finally:
        delegated.close()


@pytest.fixture
def budget_runtime(receipt_database: tuple[str, str]) -> tuple[ReceiptRuntime, dict[str, Any]]:
    runtime = create_multiline_runtime(receipt_database)
    with runtime.actor(MAKER) as (connection, _, _):
        identities = PostgresIdentityRepository(connection)
        scopes = PostgresScopeAuthorityRepository(connection)
        for permission in ("budget_control.read", "budget_control.manage", "budget_control.approve"):
            identities.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identities.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
        for name in (MAKER, CHECKER, POSTER):
            user = identities.get_user_by_id(tenant_id=runtime.tenant, user_id="id-" + name)
            assert user is not None
            for scope_type, scope_id in (("workspace", "work"), ("organization", "org"), ("legal_entity", "entity")):
                scopes.grant(tenant_id=runtime.tenant, grant_id="grant-" + name + scope_type, principal_type="user",
                             principal_id=user.id, scope_type=scope_type, scope_id=scope_id, actor_id=user.id)
    with runtime.actor(MAKER) as (connection, _, _):
        repo = PostgresBudgetControlRepository(connection, runtime.tenant)
        budget = repo.create(SCOPE, BudgetDefinition("PROCURE", "Synthetic purchase appropriation", "period", "USD", 20000), command_id="budget-create")
        budget = repo.transition(SCOPE, budget["id"], action="submit", expected_version=budget["row_version"], reason="Submit appropriation", command_id="budget-submit")
    with runtime.actor(CHECKER) as (connection, _, _):
        budget = PostgresBudgetControlRepository(connection, runtime.tenant).transition(SCOPE, budget["id"], action="approve",
            expected_version=budget["row_version"], reason="Independent appropriation approval", command_id="budget-approve")
    return runtime, budget


def create(runtime: ReceiptRuntime, budget: dict[str, Any], number: str = "BPC1-PO-1") -> tuple[dict[str, Any], dict[str, Any]]:
    with runtime.actor(MAKER) as (connection, _, actor):
        repo = PostgresProcurementCommitmentRepository(connection, runtime.tenant)
        request = BudgetPurchasePreparation(budget_id=budget["id"], expected_budget_version=budget["row_version"], order=enterprise_request(number), reason="Appropriated exact native purchase")
        owner = repo.create(request, command_id="budget-po-create", actor=actor)
        assert repo.create(request, command_id="budget-po-create", actor=actor) == owner
        purchase = repo.purchase.get(owner["order_id"], actor=actor)
        envelope = repo.budgets.get(SCOPE, budget["id"])
        assert (envelope["reserved_minor"], envelope["consumed_minor"], envelope["available_minor"]) == ("17000", "0", "3000")
    return owner, action(runtime, action(runtime, purchase, "submit-order", MAKER), "approve-order", CHECKER)


def reviewed_invoice(runtime: ReceiptRuntime, purchase: dict[str, Any]) -> tuple[dict[str, Any], str]:
    purchase = receive_line(runtime, purchase, 0, "2")
    purchase = receive_line(runtime, purchase, 1, "2.50")
    purchase = invoice_lines(runtime, purchase, ((0, "2"), (1, "2.50")))
    identifier = purchase["invoices"][-1]["id"]
    for operation, actor_name in (("approve-invoice", CHECKER), ("prepare-accrual", MAKER), ("review-accrual", CHECKER)):
        purchase = action(runtime, purchase, operation, actor_name, identifier)
    return purchase, identifier


def test_actual_partial_ap_consumption_terminal_release_and_exact_retry(budget_runtime: tuple[ReceiptRuntime, dict[str, Any]]) -> None:
    runtime, budget = budget_runtime
    owner, purchase = create(runtime, budget)
    import psycopg
    with runtime.actor(MAKER) as (connection, _, _), pytest.raises(psycopg.errors.CheckViolation, match="commitment evidence is immutable"), connection.transaction():
        connection.execute("UPDATE reconforge.procurement_commitment_plans SET payload=payload||'{\"restored_attack\":true}'::jsonb WHERE tenant_id=%s AND order_id=%s", (runtime.tenant, owner["order_id"]))
    purchase, invoice_id = reviewed_invoice(runtime, purchase)
    with runtime.actor(POSTER) as (connection, _, actor):
        repo = PostgresProcurementCommitmentRepository(connection, runtime.tenant)
        arguments = dict(expected_order_version=purchase["order"]["row_version"], expected_budget_version=owner["budget_version"], command_id="consume-ap", reason="Publish native invoice and consume appropriation", actor=actor)
        consumed = repo.consume_invoice(owner["order_id"], invoice_id, **arguments)
        assert repo.consume_invoice(owner["order_id"], invoice_id, **arguments) == consumed
        assert (consumed["reserved_minor"], consumed["consumed_minor"], consumed["remaining_minor"]) == ("9600", "7400", "9600")
        purchase = repo.purchase.get(owner["order_id"], actor=actor)
        envelope = repo.budgets.get(SCOPE, budget["id"])
        assert (envelope["reserved_minor"], envelope["consumed_minor"], envelope["available_minor"]) == ("9600", "7400", "3000")
    with runtime.actor(CHECKER) as (connection, _, actor):
        repo = PostgresProcurementCommitmentRepository(connection, runtime.tenant)
        args = dict(expected_order_version=purchase["order"]["row_version"], expected_budget_version=consumed["budget_version"], posting_date="2026-10-04", command_id="release-unreceived", reason="Close remaining unreceived purchase", actor=actor)
        released = repo.release(owner["order_id"], **args)
        assert repo.release(owner["order_id"], **args) == released
        assert (released["status"], released["reserved_minor"], released["released_minor"], released["consumed_minor"]) == ("Released", "0", "9600", "7400")
        envelope = repo.budgets.get(SCOPE, budget["id"])
        assert (envelope["reserved_minor"], envelope["consumed_minor"], envelope["available_minor"]) == ("0", "7400", "12600")
        rows = connection.execute("SELECT remaining_value_minor FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchall()
        assert sum(row["remaining_value_minor"] for row in rows) == 2 * 1200 + 250 * 2000 // 100
        assert repo.get(owner["order_id"], actor=actor) == released
    # Existing governed installments settle native AP after the PO remainder is
    # released. Integer oracle derives expected inventory/AP/cash independently.
    pay_invoice(runtime, purchase["invoices"][0]["native_invoice_id"], 2400, "budget-payment-1", "2026-10-04")
    pay_invoice(runtime, purchase["invoices"][0]["native_invoice_id"], 5000, "budget-payment-2", "2026-10-04")
    with runtime.actor(POSTER) as (connection, _, actor):
        repo = PostgresProcurementCommitmentRepository(connection, runtime.tenant)
        detail = repo.purchase.get(owner["order_id"], actor=actor)
        assert (detail["totals"]["paid_minor"], detail["totals"]["outstanding_minor"]) == ("7400", "0")
        assert repo.get(owner["order_id"], actor=actor) == released
        assert tuple(connection.execute("SELECT sum(debit_minor),sum(credit_minor) FROM reconforge.finance_entry_lines WHERE tenant_id=%s", (runtime.tenant,)).fetchone()) == (3 * 7400, 3 * 7400)


def test_detached_ap_publication_and_self_release_refused(budget_runtime: tuple[ReceiptRuntime, dict[str, Any]]) -> None:
    runtime, budget = budget_runtime
    owner, purchase = create(runtime, budget)
    with runtime.actor(MAKER) as (connection, _, actor):
        repo = PostgresProcurementCommitmentRepository(connection, runtime.tenant)
        with pytest.raises(ProcurementPartialError, match="independent"):
            repo.release(owner["order_id"], expected_order_version=purchase["order"]["row_version"], expected_budget_version=owner["budget_version"],
                         posting_date="2026-10-04", command_id="self-release", reason="Self approval attempt", actor=actor)
    purchase, invoice_id = reviewed_invoice(runtime, purchase)
    with pytest.raises(ProcurementPartialError, match="appropriation"):
        action(runtime, purchase, "post-accrual", POSTER, invoice_id)


def snapshot(runtime: ReceiptRuntime) -> str:
    from psycopg import sql
    with runtime.actor(MAKER) as (connection, _, _):
        captured = {"native": enterprise_digest(connection, runtime.tenant)}
        for table in ("budget_envelopes", "budget_commitment_events", "budget_commands", "procurement_commitment_plans", "procurement_commitment_commands"):
            captured[table] = [row["payload"] for row in connection.execute(sql.SQL(
                "SELECT to_jsonb(t) AS payload FROM reconforge.{} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text").format(sql.Identifier(table)), (runtime.tenant,)).fetchall()]
        return digest_payload(captured)


@pytest.mark.parametrize("boundary", ["after-budget", "after-gl"])
def test_fault_after_native_budget_or_gl_rolls_back_entire_cycle(budget_runtime: tuple[ReceiptRuntime, dict[str, Any]], monkeypatch: pytest.MonkeyPatch, boundary: str) -> None:
    runtime, budget = budget_runtime
    owner, purchase = create(runtime, budget)
    purchase, invoice = reviewed_invoice(runtime, purchase)
    before = snapshot(runtime)
    def failed(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Injected native publication response loss before commit")
    with pytest.raises(RuntimeError, match="Injected"), runtime.actor(POSTER) as (connection, _, actor):
        repo = PostgresProcurementCommitmentRepository(connection, runtime.tenant)
        monkeypatch.setattr(repo.purchase if boundary == "after-budget" else repo, "act" if boundary == "after-budget" else "_remember", failed)
        repo.consume_invoice(owner["order_id"], invoice, expected_order_version=purchase["order"]["row_version"],
            expected_budget_version=owner["budget_version"], command_id="fault-consume", reason="Atomic appropriation and AP", actor=actor)
    assert snapshot(runtime) == before


@pytest.mark.parametrize("target", ["owner", "response", "event", "audit", "orphan"])
def test_raw_sql_owner_evidence_and_orphan_cannot_diverge(budget_runtime: tuple[ReceiptRuntime, dict[str, Any]], target: str) -> None:
    import psycopg
    runtime, budget = budget_runtime
    owner, _ = create(runtime, budget)
    before = snapshot(runtime)
    with pytest.raises(psycopg.Error), runtime.actor(MAKER) as (connection, _, _):
        if target == "owner":
            connection.execute("UPDATE reconforge.procurement_commitment_plans SET payload=jsonb_set(payload,'{amount_minor}','1') WHERE tenant_id=%s", (runtime.tenant,))
        elif target == "response":
            connection.execute("UPDATE reconforge.procurement_commitment_commands SET response_json=jsonb_set(response_json,'{remaining_minor}','\"1\"') WHERE tenant_id=%s", (runtime.tenant,))
        elif target == "event":
            connection.execute("DELETE FROM reconforge.budget_commitment_events WHERE tenant_id=%s AND id=%s", (runtime.tenant, owner["evidence"]["budget_event_id"]))
        elif target == "audit":
            connection.execute("DELETE FROM reconforge.domain_audit_events WHERE tenant_id=%s AND id=%s", (runtime.tenant, owner["evidence"]["audit_event_id"]))
        else:
            connection.execute("DELETE FROM reconforge.procurement_partial_orders WHERE tenant_id=%s AND id=%s", (runtime.tenant, owner["order_id"]))
    assert snapshot(runtime) == before


def test_reserved_native_namespace_without_budget_owner_is_refused(budget_runtime: tuple[ReceiptRuntime, dict[str, Any]]) -> None:
    import psycopg
    runtime, _ = budget_runtime
    before = snapshot(runtime)
    with pytest.raises(psycopg.errors.CheckViolation, match="appropriation"), runtime.actor(MAKER) as (connection, _, actor):
        PostgresProcurementCommitmentRepository(connection, runtime.tenant).purchase.create_multiline(
            enterprise_request("BPC1-ORPHAN"), command_id="orphan-purchase", actor=actor)
    assert snapshot(runtime) == before


@pytest.mark.parametrize("revocation", ["permission", "scope"])
def test_lost_response_retry_requires_current_budget_authority(budget_runtime: tuple[ReceiptRuntime, dict[str, Any]], revocation: str) -> None:
    runtime, budget = budget_runtime
    owner, _ = create(runtime, budget)
    request = BudgetPurchasePreparation(budget_id=budget["id"], expected_budget_version=budget["row_version"],
        order=enterprise_request("BPC1-PO-1"), reason="Appropriated exact native purchase")
    with runtime.actor(CHECKER) as (connection, _, _):
        if revocation == "permission":
            connection.execute("UPDATE reconforge.identity_role_permissions SET active=FALSE,lifecycle_version=lifecycle_version+1,revoked_at=now(),revoked_by=%s,revocation_reason_code='access_change' WHERE tenant_id=%s AND permission_name='budget_control.manage'", ("id-" + CHECKER, runtime.tenant))
        else:
            PostgresScopeAuthorityRepository(connection).revoke(tenant_id=runtime.tenant, grant_id="grant-" + MAKER + "legal_entity", actor_id="id-" + CHECKER, reason="Revoke after lost response")
    before = snapshot(runtime)
    with pytest.raises(BudgetControlError), runtime.actor(MAKER) as (connection, _, actor):
        PostgresProcurementCommitmentRepository(connection, runtime.tenant).create(request, command_id="budget-po-create", actor=actor)
    assert snapshot(runtime) == before
    with runtime.actor(CHECKER) as (connection, _, _):
        assert connection.execute("SELECT response_json FROM reconforge.procurement_commitment_commands WHERE tenant_id=%s AND command_id='budget-po-create'", (runtime.tenant,)).fetchone()["response_json"] == owner


def test_retained_precision_cannot_reinterpret_current_bounded_authority(budget_runtime: tuple[ReceiptRuntime, dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    from decimal import Decimal

    import psycopg

    from reconforge.auth.policy import evaluate_principal_access
    from reconforge.infrastructure import budget_control_repository

    runtime, budget = budget_runtime
    owner, _ = create(runtime, budget)
    request = BudgetPurchasePreparation(budget_id=budget["id"], expected_budget_version=budget["row_version"],
        order=enterprise_request("BPC1-PO-1"), reason="Appropriated exact native purchase")
    observed: list[Decimal] = []
    def bounded_policy(*args: Any, **kwargs: Any) -> Any:
        observed.append(kwargs["amount"])
        return evaluate_principal_access(*args, **kwargs, maximum_amount=Decimal("20.00"))
    monkeypatch.setattr(budget_control_repository, "evaluate_principal_access", bounded_policy)
    with pytest.raises(BudgetControlError, match="current policy"), runtime.actor(MAKER) as (connection, _, actor):
        PostgresProcurementCommitmentRepository(connection, runtime.tenant).get(owner["order_id"], actor=actor)
    assert observed == [Decimal("170.00")]
    before = snapshot(runtime)
    # Ordinary SQL cannot change bound monetary metadata. Emulate a damaged
    # administrator-restored catalog explicitly, without changing app ACLs or
    # any retained source, budget, evidence, or financial posting row.
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"), runtime.actor(MAKER) as (connection, _, _):
        connection.execute("UPDATE reconforge.currencies SET minor_units=3 WHERE tenant_id=%s AND code='USD'", (runtime.tenant,))
    with psycopg.connect(runtime.admin_dsn) as admin:
        admin.execute("SET LOCAL session_replication_role=replica")
        admin.execute("UPDATE reconforge.currencies SET minor_units=3 WHERE tenant_id=%s AND code='USD'", (runtime.tenant,))
    for operation in ("owner-read", "owner-retry", "native-read", "native-page", "native-retry", "sql-closure"):
        with pytest.raises((psycopg.errors.CheckViolation, ProcurementPartialError), match="precision"), runtime.actor(MAKER) as (connection, _, actor):
            repo = PostgresProcurementCommitmentRepository(connection, runtime.tenant)
            if operation == "owner-read":
                repo.get(owner["order_id"], actor=actor)
            elif operation == "owner-retry":
                repo.create(request, command_id="budget-po-create", actor=actor)
            elif operation == "native-read":
                repo.purchase.get(owner["order_id"], actor=actor)
            elif operation == "native-page":
                repo.purchase.order_page("work", actor=actor)
            elif operation == "native-retry":
                repo.purchase.create_multiline(request.order, command_id="unused-native-retry", actor=actor)
            else:
                connection.execute("SELECT reconforge.pc_close(%s,%s)", (runtime.tenant, owner["order_id"]))
    assert observed == [Decimal("170.00")]
    assert snapshot(runtime) == before


@pytest.mark.parametrize("permission,operation", [("budget_control.read", "read"), ("budget_control.manage", "replay")])
def test_native_owned_projection_and_retry_require_current_budget_grant(budget_runtime: tuple[ReceiptRuntime, dict[str, Any]], permission: str, operation: str) -> None:
    runtime, budget = budget_runtime
    owner, _ = create(runtime, budget)
    with runtime.actor(CHECKER) as (connection, _, _):
        connection.execute("UPDATE reconforge.identity_role_permissions SET active=FALSE,lifecycle_version=lifecycle_version+1,revoked_at=now(),revoked_by=%s,revocation_reason_code='access_change' WHERE tenant_id=%s AND permission_name=%s", ("id-" + CHECKER, runtime.tenant, permission))
    before = snapshot(runtime)
    with pytest.raises(ProcurementPartialError, match="authority"), runtime.actor(MAKER) as (connection, _, actor):
        purchase = PostgresProcurementCommitmentRepository(connection, runtime.tenant).purchase
        if operation == "read":
            purchase.get(owner["order_id"], actor=actor)
        else:
            purchase.create_multiline(enterprise_request("BPC1-PO-1"), command_id="unused-native-replay", actor=actor)
    assert snapshot(runtime) == before


def test_two_concurrent_purchase_obligations_share_one_appropriation_limit(budget_runtime: tuple[ReceiptRuntime, dict[str, Any]]) -> None:
    runtime, budget = budget_runtime
    def attempt(number: str) -> str:
        try:
            with runtime.actor(MAKER) as (connection, _, actor):
                PostgresProcurementCommitmentRepository(connection, runtime.tenant).create(BudgetPurchasePreparation(
                    budget_id=budget["id"], expected_budget_version=budget["row_version"], order=enterprise_request(number), reason="Concurrent appropriation"), command_id=number, actor=actor)
            return "created"
        except BudgetControlError:
            return "refused"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ("BPC1-CONCURRENT-A", "BPC1-CONCURRENT-B")))
    assert sorted(outcomes) == ["created", "refused"]
    with runtime.actor(CHECKER) as (connection, _, _):
        envelope = PostgresBudgetControlRepository(connection, runtime.tenant).get(SCOPE, budget["id"])
        assert (envelope["reserved_minor"], envelope["available_minor"]) == ("17000", "3000")
        assert connection.execute("SELECT count(*) FROM reconforge.procurement_commitment_plans WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 1


def test_released_purchase_receiving_overlap_has_single_serial_outcome(budget_runtime: tuple[ReceiptRuntime, dict[str, Any]]) -> None:
    import psycopg
    runtime, budget = budget_runtime
    owner, purchase = create(runtime, budget)
    started = Event()
    pids: dict[str, int] = {}
    def prepare() -> str:
        with runtime.actor(MAKER) as (connection, _, actor):
            pids["receipt"] = connection.execute("SELECT pg_backend_pid() AS id").fetchone()["id"]
            started.set()
            try:
                PostgresProcurementCommitmentRepository(connection, runtime.tenant).purchase.prepare_receipt_line(owner["order_id"], purchase["lines"][0]["id"],
                    PartialQuantityPreparation(quantity="1", posting_date="2026-10-04", period_id="period", reason="Competing native receiving"),
                    expected_version=purchase["order"]["row_version"], command_id="competing-receipt", actor=actor)
            except psycopg.errors.CheckViolation:
                return "refused"
            return "received"
    with ThreadPoolExecutor(max_workers=1) as pool:
        with runtime.actor(CHECKER) as (connection, _, actor):
            repo = PostgresProcurementCommitmentRepository(connection, runtime.tenant)
            repo._lock(owner["order_id"], actor, "approve-order")
            holder = connection.execute("SELECT pg_backend_pid() AS id").fetchone()["id"]
            pending = pool.submit(prepare)
            assert started.wait(10)
            with psycopg.connect(runtime.admin_dsn, autocommit=True) as observer:
                deadline = monotonic() + 10
                while monotonic() < deadline and holder not in observer.execute("SELECT pg_blocking_pids(%s)", (pids["receipt"],)).fetchone()[0]:
                    sleep(0.02)
                assert holder in observer.execute("SELECT pg_blocking_pids(%s)", (pids["receipt"],)).fetchone()[0]
            repo.release(owner["order_id"], expected_order_version=purchase["order"]["row_version"], expected_budget_version=owner["budget_version"],
                posting_date="2026-10-04", command_id="serial-release", reason="Independent unreceived release", actor=actor)
        assert pending.result(timeout=20) == "refused"
    with runtime.actor(MAKER) as (connection, _, actor):
        detail = PostgresProcurementCommitmentRepository(connection, runtime.tenant).purchase.get(owner["order_id"], actor=actor)
        assert not detail["receipts"] and detail["order"]["row_version"] == purchase["order"]["row_version"]


def test_charged_receipt_on_reserved_merchandise_is_refused_and_retained_ordinary_roles_work(budget_runtime: tuple[ReceiptRuntime, dict[str, Any]], receipt_database: tuple[str, str]) -> None:
    import psycopg
    from psycopg import sql

    from reconforge.infrastructure.postgres_landed_cost import PostgresLandedCostRepository
    from tests.test_postgres_landed_cost import request as landed_request
    runtime, budget = budget_runtime
    owner, purchase = create(runtime, budget)
    before = snapshot(runtime)
    with pytest.raises(psycopg.errors.CheckViolation, match="appropriation"), runtime.actor(MAKER) as (connection, _, actor):
        PostgresLandedCostRepository(connection, runtime.tenant).prepare(landed_request(purchase), command_id="unappropriated-charges", actor=actor)
    assert snapshot(runtime) == before
    app_user = psycopg.conninfo.conninfo_to_dict(receipt_database[1])["user"]
    with psycopg.connect(receipt_database[0]) as admin:
        for table in ("procurement_commitment_plans", "procurement_commitment_commands"):
            admin.execute(sql.SQL("REVOKE SELECT ON reconforge.{} FROM {}").format(sql.Identifier(table), sql.Identifier(app_user)))
    try:
        with runtime.actor(MAKER) as (connection, _, actor):
            ordinary = PostgresProcurementCommitmentRepository(connection, runtime.tenant).purchase.create_multiline(
                enterprise_request("ORDINARY-WITHOUT-BUDGET-ACL"), command_id="ordinary-without-acl", actor=actor)
            assert ordinary["order"]["total_minor"] == "17000"
        ordinary = action(runtime, action(runtime, ordinary, "submit-order", MAKER), "approve-order", CHECKER)
        assert receive_line(runtime, ordinary, 0, "1")["totals"]["received_minor"] == "1200"
        with pytest.raises(psycopg.errors.InsufficientPrivilege), runtime.actor(MAKER) as (connection, _, actor):
            PostgresProcurementCommitmentRepository(connection, runtime.tenant).get(owner["order_id"], actor=actor)
    finally:
        with psycopg.connect(receipt_database[0]) as admin:
            for table in ("procurement_commitment_plans", "procurement_commitment_commands"):
                admin.execute(sql.SQL("GRANT SELECT ON reconforge.{} TO {}").format(sql.Identifier(table), sql.Identifier(app_user)))


def test_concurrent_same_ap_command_commits_one_budget_and_financial_effect(budget_runtime: tuple[ReceiptRuntime, dict[str, Any]]) -> None:
    runtime, budget = budget_runtime
    owner, purchase = create(runtime, budget)
    purchase, invoice = reviewed_invoice(runtime, purchase)
    def consume() -> dict[str, Any]:
        with runtime.actor(POSTER) as (connection, _, actor):
            return PostgresProcurementCommitmentRepository(connection, runtime.tenant).consume_invoice(owner["order_id"], invoice,
                expected_order_version=purchase["order"]["row_version"], expected_budget_version=owner["budget_version"],
                command_id="same-ap-outcome", reason="Concurrent response-loss retry", actor=actor)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: consume(), range(2)))
    assert results[0] == results[1] and results[0]["consumed_minor"] == "7400"
    with runtime.actor(CHECKER) as (connection, _, _):
        assert connection.execute("SELECT count(*) FROM reconforge.procurement_commitment_commands WHERE tenant_id=%s AND operation='consume'", (runtime.tenant,)).fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 3


def test_actual_ordered_upgrade_empty_rollback_and_populated_refusal_preserve_native_history() -> None:
    import os
    import subprocess
    import sys
    from pathlib import Path

    import psycopg
    from psycopg import sql

    from tests.test_postgres_procurement_multiline import create_order
    delegated = base_receipt_database.__wrapped__()
    try:
        database = next(delegated)
        runtime = create_multiline_runtime(database)
        ordinary = receive_line(runtime, create_order(runtime, "PRIOR-0125-SOURCE"), 0, "1")
        before = snapshot(runtime)
        app_user = psycopg.conninfo.conninfo_to_dict(database[1])["user"]
        with psycopg.connect(database[0]) as admin:
            for table in ("procurement_commitment_plans", "procurement_commitment_commands"):
                assert all(admin.execute("SELECT has_table_privilege(%s,%s,%s)", (app_user, "reconforge." + table, permission)).fetchone()[0]
                    for permission in ("SELECT", "INSERT", "UPDATE", "DELETE"))
        env = {**os.environ, "RECONFORGE_POSTGRES_DSN": database[0]}
        root = Path(__file__).resolve().parents[1]
        for target in ("0125_pg_landed_cost_cancellation", "head"):
            operation = "upgrade" if target == "head" else "downgrade"
            result = subprocess.run([sys.executable, "-m", "alembic", operation, target], cwd=root, env=env,
                capture_output=True, text=True, timeout=180, check=False)
            assert result.returncode == 0, result.stderr[-3000:]
        # Empty rollback recreates tables. Restore exactly the native app ACL
        # confirmed above, as the deployment upgrade/role bootstrap must do.
        with psycopg.connect(database[0]) as admin:
            for table in ("procurement_commitment_plans", "procurement_commitment_commands"):
                admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{} TO {}").format(sql.Identifier(table), sql.Identifier(app_user)))
        assert snapshot(runtime) == before
        with runtime.actor(MAKER) as (connection, _, actor):
            assert PostgresProcurementCommitmentRepository(connection, runtime.tenant).purchase.get(ordinary["order"]["id"], actor=actor) == ordinary
        reserved_runtime, budget = budget_runtime.__wrapped__(database)
        create(reserved_runtime, budget)
        retained = snapshot(reserved_runtime)
        refused = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0125_pg_landed_cost_cancellation"], cwd=root, env=env,
            capture_output=True, text=True, timeout=180, check=False)
        assert refused.returncode != 0 and "Retained appropriation history" in refused.stderr
        assert snapshot(reserved_runtime) == retained
        with psycopg.connect(database[0]) as admin:
            assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0127_pg_procurement_commitments"
    finally:
        delegated.close()


@pytest.mark.parametrize("operation", ["Consume", "Release"])
def test_existing_budget_commands_cannot_detach_owned_purchase_effects(budget_runtime: tuple[ReceiptRuntime, dict[str, Any]], operation: str) -> None:
    import psycopg
    runtime, budget = budget_runtime
    owner, _ = create(runtime, budget)
    before = snapshot(runtime)
    with pytest.raises(psycopg.errors.CheckViolation, match="appropriation"), runtime.actor(MAKER) as (connection, _, _):
        PostgresBudgetControlRepository(connection, runtime.tenant).record(SCOPE, budget["id"],
            CommitmentAction(operation, 1000, "2026-10-04", "BPC1:" + owner["order_id"], "Detach native source"),
            expected_version=owner["budget_version"], commitment_id=owner["commitment_id"], command_id="detached-budget-event")
    assert snapshot(runtime) == before
