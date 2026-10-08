"""Actual restricted-role receipt commands with persisted, password-authenticated humans."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.inventory_receipt_posting import (
    COMMIT_PERMISSIONS,
    PREPARE_PERMISSIONS,
    READ_PERMISSIONS,
    REVIEW_PERMISSIONS,
    ReceiptPreparation,
    ReceiptReversalPreparation,
)
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_inventory_receipt_posting import PostgresInventoryReceiptPostingRepository
from reconforge.infrastructure.postgres_inventory_valuation import PostgresInventoryValuationRepository
from reconforge.platform.common import ServerPrincipal, server_principal_context

pytestmark = pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"), reason="requires owned live PostgreSQL fixture")
PERMISSIONS = PREPARE_PERMISSIONS | REVIEW_PERMISSIONS | COMMIT_PERMISSIONS | READ_PERMISSIONS | frozenset({"inventory.valuation.reverse.manage", "inventory.valuation.reverse.approve", "finance_core.reverse"})


@dataclass
class ReceiptRuntime:
    factory: PostgresConnectionFactory
    admin_dsn: str
    tenant: str
    password: str

    @contextmanager
    def actor(self, name: str) -> Iterator[tuple[Any, PostgresInventoryReceiptPostingRepository, PostingActor]]:
        boundary = PostgresTenantBoundary(self.factory)
        with boundary.transaction(self.tenant) as connection:
            identities = PostgresIdentityRepository(connection)
            user = identities.authenticate_user(tenant_id=self.tenant, username=name, password=self.password)
            assert user is not None
            permissions = identities.user_permissions(tenant_id=self.tenant, user_id=user.id)
        with boundary.transaction(self.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity") as connection:
            principal = ServerPrincipal(user=user, permissions=permissions, step_up_active=True,
                authorized_tenant_ids=frozenset({self.tenant}), authorized_workspace_ids=frozenset({"work"}),
                authorized_organization_ids=frozenset({"org"}), authorized_legal_entity_ids=frozenset({"entity"}))
            with server_principal_context(principal):
                yield connection, PostgresInventoryReceiptPostingRepository(connection, self.tenant), PostingActor(user.id, user.username, permissions, step_up_active=True)


@pytest.fixture(scope="module")
def receipt_database() -> Iterator[tuple[str, str]]:
    import psycopg
    from psycopg import sql
    database = "reconforge_irp_" + uuid4().hex[:12]
    admin_url = urlsplit(os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"])
    admin_dsn = urlunsplit(admin_url._replace(path="/" + database))
    app_dsn = psycopg.conninfo.make_conninfo(os.environ["RECONFORGE_TEST_POSTGRES_DSN"], dbname=database)
    control_dsn = psycopg.conninfo.make_conninfo(admin_dsn, dbname="postgres", connect_timeout=5)
    with psycopg.connect(control_dsn, autocommit=True) as control:
        control.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "RECONFORGE_POSTGRES_DSN": admin_dsn}, check=True, timeout=180)
        from reconforge.infrastructure.postgres_inventory_receipt_posting_schema import (
            install_postgres_inventory_receipt_posting_schema,
        )
        with psycopg.connect(admin_dsn) as admin:
            install_postgres_inventory_receipt_posting_schema(admin)
            from reconforge.infrastructure.postgres_receipt_admission import install_postgres_receipt_admission
            install_postgres_receipt_admission(admin)
            app_user = psycopg.conninfo.conninfo_to_dict(app_dsn)["user"]
            for statement in ("GRANT USAGE ON SCHEMA reconforge TO {}", "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}", "GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {}"):
                admin.execute(sql.SQL(statement).format(sql.Identifier(app_user)))
        yield admin_dsn, app_dsn
    finally:
        with psycopg.connect(control_dsn, autocommit=True) as control:
            control.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
            assert control.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone() is None


def create_receipt_runtime(receipt_database: tuple[str, str]) -> ReceiptRuntime:
    import psycopg
    admin_dsn, app_dsn = receipt_database
    tenant, password = "irp-" + uuid4().hex[:12], "Synthetic-IRP-" + uuid4().hex
    with psycopg.connect(admin_dsn) as admin:
        admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,'Synthetic IRP')", (tenant,))
    factory = PostgresConnectionFactory(PostgresSettings(dsn=app_dsn, require_tls=False))
    with PostgresTenantBoundary(factory).transaction(tenant) as connection:
        connection.execute("INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,'work','work')", (tenant,))
        connection.execute("INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES(%s,'USD','US Dollar',2)", (tenant,))
        connection.execute("INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,base_currency,application_workspace_id) VALUES(%s,'org','ORG','Synthetic','USD','work')", (tenant,))
        connection.execute("INSERT INTO reconforge.master_data_workspace_organizations(tenant_id,workspace_id,organization_id) VALUES(%s,'work','org')", (tenant,))
        connection.execute("INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) VALUES(%s,'entity','org','ENTITY','Synthetic','USD')", (tenant,))
        connection.execute("INSERT INTO reconforge.fiscal_periods(tenant_id,id,name,start_date,end_date,fiscal_year,period_number,application_workspace_id) VALUES(%s,'period','2026-10','2026-10-01','2026-10-31',2026,10,'work')", (tenant,))
        connection.execute("INSERT INTO reconforge.master_data_workspace_periods(tenant_id,workspace_id,period_id) VALUES(%s,'work','period')", (tenant,))
        finance = PostgresFinanceCoreRepository(connection, tenant)
        finance.upsert_chart(chart_code="DEFAULT", name="Synthetic", workspace="work", organization_code="ORG")
        for account, kind in (("INVENTORY", "Asset"), ("CLEARING", "Liability"), ("COGS", "Expense"), ("ADJUSTMENT", "Expense")):
            finance.upsert_account(account_code=account, name=account, account_type=kind, chart_code="DEFAULT", workspace="work")
        finance.upsert_journal(journal_code="STOCK", name="Synthetic", organization_code="ORG", currency_code="USD", workspace="work")
        inventory = PostgresInventoryCoreRepository(connection, tenant)
        inventory.upsert_uom(uom_code="EA", name="Each", decimal_places=0, workspace="work")
        inventory.upsert_item(item_code="ITEM", name="Synthetic item", organization_code="ORG", uom_code="EA", inventory_account_code="INVENTORY", workspace="work")
        inventory.upsert_warehouse(warehouse_code="MAIN", name="Synthetic", organization_code="ORG", entity_code="ENTITY", workspace="work")
        inventory.upsert_location(warehouse_code="MAIN", location_code="STOCK", name="Synthetic", organization_code="ORG", workspace="work")
        PostgresInventoryValuationRepository(connection, tenant).upsert_policy(policy_code="FIFO", organization_code="ORG", entity_code="ENTITY", journal_code="STOCK", receipt_clearing_account_code="CLEARING", cogs_account_code="COGS", adjustment_account_code="ADJUSTMENT", workspace="work")
        identities = PostgresIdentityRepository(connection)
        identities.create_role(tenant_id=tenant, role_name="receipt-operator")
        for permission in sorted(PERMISSIONS):
            identities.create_permission(tenant_id=tenant, permission_name=permission)
            identities.grant_permission(tenant_id=tenant, role_name="receipt-operator", permission_name=permission)
        for name in ("maker", "checker", "poster"):
            identities.create_user(tenant_id=tenant, user_id=name, username=name, password=password, role_name="receipt-operator")
    return ReceiptRuntime(factory, admin_dsn, tenant, password)


@pytest.fixture
def receipt_runtime(receipt_database: tuple[str, str]) -> ReceiptRuntime:
    return create_receipt_runtime(receipt_database)


def request(number: str = "RECEIPT-1") -> ReceiptPreparation:
    return ReceiptPreparation(receipt_number=number, posting_date="2026-10-03", period_id="period", item_code="ITEM",
        location_code="MAIN/STOCK", quantity="10", total_value_minor=12000, policy_code="FIFO", organization_code="ORG",
        entity_code="ENTITY", workspace="work", reason="Reviewed synthetic receipt")


def prepare_and_review(runtime: ReceiptRuntime) -> tuple[Any, Any]:
    with runtime.actor("maker") as (_, repository, actor):
        plan = repository.prepare_receipt(request(), command_id="prepare-1", actor=actor)
    with runtime.actor("checker") as (_, repository, actor):
        review = repository.review(plan["plan_id"], command_id="review-1", expected_plan_digest=plan["plan_digest"], reason="Verified quantity and total", actor=actor)
    return plan, review


def test_actual_reviewed_receipt_ten_units_12000_minor_and_exact_lost_ack(receipt_runtime: ReceiptRuntime) -> None:
    runtime = receipt_runtime
    plan, review = prepare_and_review(runtime)
    with runtime.actor("poster") as (connection, repository, actor):
        effect = repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish complete source", actor=actor)
        assert effect["source_kind"] == "InventoryReceipt"
        assert [line["debit_minor"] for line in effect["finance_effect"]["snapshot"]["lines"]] == [12000, 0]
        assert [line["credit_minor"] for line in effect["finance_effect"]["snapshot"]["lines"]] == [0, 12000]
        assert dict(connection.execute("SELECT remaining_quantity_scaled,remaining_value_minor FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND id=%s", (runtime.tenant, effect["cost_layer_id"])).fetchone()) == {"remaining_quantity_scaled": 10, "remaining_value_minor": 12000}
    with runtime.actor("checker") as (connection, repository, actor):
        assert repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish complete source", actor=actor) == effect
        assert repository.get_effect(plan["plan_id"], actor=actor) == effect
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1


def test_actual_reviewed_full_unused_inverse_zero_stock_and_period_net(receipt_runtime: ReceiptRuntime) -> None:
    runtime = receipt_runtime
    plan, review = prepare_and_review(runtime)
    with runtime.actor("poster") as (_, repository, actor):
        original = repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Receipt", actor=actor)
    with runtime.actor("maker") as (_, repository, actor):
        inverse = repository.prepare_reversal(ReceiptReversalPreparation(original_plan_id=plan["plan_id"], reversal_number="REVERSE-1", posting_date="2026-10-04", period_id="period", reason="Full receipt correction"), command_id="inverse-prepare", actor=actor)
    with runtime.actor("checker") as (_, repository, actor):
        inverse_review = repository.review(inverse["plan_id"], command_id="inverse-review", expected_plan_digest=inverse["plan_digest"], reason="Confirmed entirely unused source", actor=actor)
    with runtime.actor("poster") as (connection, repository, actor):
        inverse_effect = repository.commit(inverse["plan_id"], command_id="inverse-commit", expected_review_digest=inverse_review["review_digest"], reason="Full inverse", actor=actor)
        assert inverse_effect["reverses_effect_id"] == original["effect_id"]
        layer = connection.execute("SELECT remaining_quantity_scaled,remaining_value_minor FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND id=%s", (runtime.tenant, original["cost_layer_id"])).fetchone()
        assert dict(layer) == {"remaining_quantity_scaled": 0, "remaining_value_minor": 0}
        balance = repository.finance.posted_trial_balance(period_id="period", organization_code="ORG", entity_code="ENTITY", workspace="work", actor=actor)
        assert balance["balance_totals"] == {"debit_minor": 0, "credit_minor": 0, "balanced": True}
        assert balance["totals"]["debit_minor"] == 24000


def test_same_human_review_and_manual_partial_reversal_refused(receipt_runtime: ReceiptRuntime) -> None:
    runtime = receipt_runtime
    with runtime.actor("maker") as (_, repository, actor):
        plan = repository.prepare_receipt(request(), command_id="prepare-1", actor=actor)
        with pytest.raises(FinancePostingError, match="preparer"):
            repository.review(plan["plan_id"], command_id="review-1", expected_plan_digest=plan["plan_digest"], reason="Self review", actor=actor)
    with runtime.actor("checker") as (_, repository, actor):
        review = repository.review(plan["plan_id"], command_id="review-1", expected_plan_digest=plan["plan_digest"], reason="Independent review", actor=actor)
        effect = repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=actor)
        with pytest.raises(FinancePostingError, match="complete source"):
            repository.finance.post(effect["entry_id"], command_id="manual", expected_validation_digest=plan["finance_validation_digest"], reason="Partial", actor=actor)
        with pytest.raises(FinancePostingError, match="full source inverse"):
            repository.finance.prepare_reversal(effect["effect_id"], command_id="manual-reversal", entry_number="PARTIAL", period_id="period", posting_date="2026-10-04", reason="Partial", actor=actor)


def backing_digest(connection, tenant):
    from psycopg import sql

    from reconforge.domain.finance_posting import digest_payload
    tables = ("inventory_movements", "inventory_movement_lines", "inventory_valuation_documents", "inventory_valuation_input_costs",
              "inventory_valuation_lines", "inventory_cost_layers", "inventory_layer_consumptions", "inventory_valuation_reversals",
              "inventory_valuation_reversal_effects", "finance_entries", "finance_entry_lines", "finance_posting_effects",
              "inventory_receipt_plans", "inventory_receipt_reviews", "inventory_receipt_links", "inventory_receipt_commands",
              "domain_audit_events", "domain_audit_ledger_state", "outbox_events", "currency_registry_snapshots", "currency_registry_bindings")
    result = {}
    for table in tables:
        rows = connection.execute(sql.SQL("SELECT to_jsonb(t) payload FROM reconforge.{} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text").format(sql.Identifier(table)), (tenant,)).fetchall()
        result[table] = [row["payload"] for row in rows]
    assert any(row["object_type"] == "inventory_receipt_posting" for row in result["domain_audit_events"])
    assert any(row["aggregate_type"] == "inventory_receipt_posting" for row in result["outbox_events"])
    return digest_payload(result)


@pytest.mark.parametrize("table", ["outbox_events", "finance_posting_effects", "inventory_receipt_commands"])
def test_late_written_effect_or_evidence_or_command_failure_rolls_back_all_layers(receipt_runtime: ReceiptRuntime, monkeypatch, table):
    runtime = receipt_runtime
    plan, review = prepare_and_review(runtime)
    with runtime.actor("poster") as (connection, repository, actor):
        before = backing_digest(connection, runtime.tenant)
        insert = repository._insert
        def failing_insert(name, values, **kwargs):
            insert(name, values, **kwargs)
            if name == table:
                raise RuntimeError("synthetic late receipt failure")
        with monkeypatch.context() as patch:
            patch.setattr(repository, "_insert", failing_insert)
            with pytest.raises(RuntimeError, match="synthetic late"):
                repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=actor)
        assert backing_digest(connection, runtime.tenant) == before
    with runtime.actor("poster") as (connection, repository, actor):
        assert backing_digest(connection, runtime.tenant) == before
        result = repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=actor)
        assert result["effect_id"] == plan["artifacts"]["posting_effect_id"]


def test_caught_python_failure_after_finance_draft_poisons_complete_owner(receipt_runtime: ReceiptRuntime, monkeypatch):
    from reconforge.infrastructure.postgres_inventory_receipt_posting import _ReceiptFinanceParticipant
    runtime = receipt_runtime
    plan, review = prepare_and_review(runtime)
    original = _ReceiptFinanceParticipant._materialize_draft
    def failing_child(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError("synthetic pure child failure after draft")
    public = _ReceiptFinanceParticipant.materialize_draft
    def caught_child(self, plan_id, **kwargs):
        try:
            return public(self, plan_id, **kwargs)
        except RuntimeError:
            assert self.owner._rollback_only
            return plan["artifacts"]["finance_entry_id"]
    with runtime.actor("poster") as (connection, repository, actor):
        before = backing_digest(connection, runtime.tenant)
        with monkeypatch.context() as patch:
            patch.setattr(_ReceiptFinanceParticipant, "_materialize_draft", failing_child)
            patch.setattr(_ReceiptFinanceParticipant, "materialize_draft", caught_child)
            with pytest.raises(FinancePostingError, match="complete owner to roll back"):
                repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=actor)
        assert backing_digest(connection, runtime.tenant) == before


def test_replay_current_human_authority_and_request_affinity_without_duplicate_evidence(receipt_runtime: ReceiptRuntime):
    from dataclasses import replace
    runtime = receipt_runtime
    plan, review = prepare_and_review(runtime)
    with runtime.actor("poster") as (connection, repository, actor):
        effect = repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=actor)
        before = backing_digest(connection, runtime.tenant)
        assert repository.prepare_receipt(replace(request(), quantity="10.000"), command_id="prepare-1", actor=actor) == plan
        assert repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=actor) == effect
        for modified in (replace(request(), total_value_minor=12001), replace(request(), quantity="11"), replace(request(), reason="Changed")):
            with pytest.raises(FinancePostingError):
                repository.prepare_receipt(modified, command_id="prepare-1", actor=actor)
        assert backing_digest(connection, runtime.tenant) == before
        denied = PostingActor(actor.user_id, actor.username, frozenset(), step_up_active=True)
        with pytest.raises(FinancePostingError):
            repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=denied)
        assert backing_digest(connection, runtime.tenant) == before


def test_existing_review_recovery_preserves_original_checker_and_refuses_new_command(receipt_runtime: ReceiptRuntime):
    runtime = receipt_runtime
    plan, review = prepare_and_review(runtime)
    with runtime.actor("poster") as (connection, repository, actor):
        before = backing_digest(connection, runtime.tenant)
        assert repository.review(plan["plan_id"], command_id="review-1", expected_plan_digest=plan["plan_digest"],
                                 reason="Verified quantity and total", actor=actor) == review
        assert review["reviewer"]["user_id"] == "checker"
        with pytest.raises(FinancePostingError, match="immutable review already exists"):
            repository.review(plan["plan_id"], command_id="review-2", expected_plan_digest=plan["plan_digest"],
                              reason="Verified quantity and total", actor=actor)
        assert backing_digest(connection, runtime.tenant) == before
    with runtime.actor("checker") as (connection, repository, actor):
        assert backing_digest(connection, runtime.tenant) == before
        assert repository.review(plan["plan_id"], command_id="review-1", expected_plan_digest=plan["plan_digest"],
                                 reason="Verified quantity and total", actor=actor) == review


def test_actual_two_connection_lost_ack_waits_for_committed_source(receipt_runtime: ReceiptRuntime):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    import psycopg
    runtime = receipt_runtime
    plan, review = prepare_and_review(runtime)
    inserted, release, second_started = threading.Event(), threading.Event(), threading.Event()
    second_pid = []
    def first():
        with runtime.actor("poster") as (_, repository, actor):
            remember = repository._remember
            def held(*args, **kwargs):
                remember(*args, **kwargs)
                inserted.set()
                assert release.wait(15)
            repository._remember = held
            return repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=actor)
    def second():
        with runtime.actor("checker") as (connection, repository, actor):
            second_pid.append(connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"])
            second_started.set()
            return repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=actor)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(first)
        try:
            assert inserted.wait(15)
            two = pool.submit(second)
            assert second_started.wait(15)
            observed = False
            with psycopg.connect(runtime.admin_dsn, autocommit=True) as control:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    row = control.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", (second_pid[0],)).fetchone()
                    if row and row[0] == "Lock":
                        observed = True
                        break
                    time.sleep(0.025)
            assert observed, "second physical backend must wait on the source transaction"
        finally:
            release.set()
        assert one.result(timeout=15) == two.result(timeout=15)
    with runtime.actor("checker") as (connection, _, _):
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1


def test_outer_owner_rollback_removes_complete_post_and_exact_evidence(receipt_runtime: ReceiptRuntime):
    runtime = receipt_runtime
    plan, review = prepare_and_review(runtime)
    with runtime.actor("poster") as (connection, repository, actor):
        before = backing_digest(connection, runtime.tenant)
        with pytest.raises(RuntimeError, match="outer rollback"), connection.transaction():
            repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=actor)
            raise RuntimeError("synthetic outer rollback")
        assert backing_digest(connection, runtime.tenant) == before
    with runtime.actor("checker") as (connection, _, _):
        assert backing_digest(connection, runtime.tenant) == before


def test_historical_receipt_replay_survives_closed_period_and_inactive_item_mapping(receipt_runtime: ReceiptRuntime):
    import psycopg
    runtime = receipt_runtime
    plan, review = prepare_and_review(runtime)
    with runtime.actor("poster") as (_, repository, actor):
        effect = repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=actor)
    with psycopg.connect(runtime.admin_dsn) as admin:
        admin.execute("UPDATE reconforge.fiscal_periods SET status='Closed' WHERE tenant_id=%s AND id='period'", (runtime.tenant,))
        admin.execute("UPDATE reconforge.inventory_items SET active=false WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["source"]["item_id"]))
        admin.execute("UPDATE reconforge.inventory_valuation_policies SET active=false WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["mapping"]["policy_id"]))
    with runtime.actor("checker") as (connection, repository, actor):
        before = backing_digest(connection, runtime.tenant)
        assert repository.prepare_receipt(request(), command_id="prepare-1", actor=actor) == plan
        assert repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=actor) == effect
        assert repository.get_effect(plan["plan_id"], actor=actor) == effect
        assert backing_digest(connection, runtime.tenant) == before


@pytest.mark.parametrize("ascending", [True, False])
def test_equal_business_date_keeps_existing_reserved_number_fifo_order(receipt_runtime: ReceiptRuntime, ascending):
    runtime = receipt_runtime
    prepared = []
    with runtime.actor("maker") as (_, repository, actor):
        for number in ("RECEIPT-A", "RECEIPT-B"):
            prepared.append(repository.prepare_receipt(request(number), command_id="prepare-" + number, actor=actor))
    prepared.sort(key=lambda plan: plan["artifacts"]["movement_number"], reverse=not ascending)
    reviews = []
    with runtime.actor("checker") as (_, repository, actor):
        for plan in prepared:
            reviews.append(repository.review(plan["plan_id"], command_id="review-" + plan["source"]["number"], expected_plan_digest=plan["plan_digest"], reason="Review", actor=actor))
    with runtime.actor("poster") as (connection, repository, actor):
        repository.commit(prepared[0]["plan_id"], command_id="commit-first", expected_review_digest=reviews[0]["review_digest"], reason="Publish", actor=actor)
        before = backing_digest(connection, runtime.tenant)
        if ascending:
            repository.commit(prepared[1]["plan_id"], command_id="commit-second", expected_review_digest=reviews[1]["review_digest"], reason="Publish", actor=actor)
            assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 2
        else:
            with pytest.raises(FinancePostingError, match="Backdated"):
                repository.commit(prepared[1]["plan_id"], command_id="commit-second", expected_review_digest=reviews[1]["review_digest"], reason="Publish", actor=actor)
            assert backing_digest(connection, runtime.tenant) == before


@pytest.mark.parametrize("posting_first", [True, False])
def test_metadata_active_update_serializes_with_real_source_admission(receipt_runtime: ReceiptRuntime, monkeypatch, posting_first):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    import psycopg
    runtime = receipt_runtime
    plan, review = prepare_and_review(runtime)
    held, release, follower_started = threading.Event(), threading.Event(), threading.Event()
    follower_pid = []
    def post():
        with runtime.actor("poster") as (connection, repository, actor):
            if posting_first:
                admit = repository._admit
                def holding_admission(*args, **kwargs):
                    admit(*args, **kwargs)
                    held.set()
                    assert release.wait(15)
                monkeypatch.setattr(repository, "_admit", holding_admission)
            else:
                follower_pid.append(connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"])
                follower_started.set()
            return repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=actor)
    def deactivate():
        with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work", organization_id="org") as connection:
            if posting_first:
                follower_pid.append(connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"])
                follower_started.set()
            connection.execute("UPDATE reconforge.finance_accounts SET active=false WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["mapping"]["inventory_account_id"]))
            if not posting_first:
                held.set()
                assert release.wait(15)
    with ThreadPoolExecutor(max_workers=2) as pool:
        leader = pool.submit(post if posting_first else deactivate)
        try:
            assert held.wait(15)
            follower = pool.submit(deactivate if posting_first else post)
            assert follower_started.wait(15)
            observed = False
            with psycopg.connect(runtime.admin_dsn, autocommit=True) as control:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    row = control.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", (follower_pid[0],)).fetchone()
                    if row and row[0] == "Lock":
                        observed = True
                        break
                    time.sleep(0.025)
            assert observed
        finally:
            release.set()
        leader_result = leader.result(timeout=15)
        if posting_first:
            follower.result(timeout=15)
            assert leader_result["source_kind"] == "InventoryReceipt"
        else:
            with pytest.raises(FinancePostingError):
                follower.result(timeout=15)
    with runtime.actor("checker") as (connection, repository, actor):
        count = connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"]
        assert count == (1 if posting_first else 0)
        if posting_first:
            assert repository.get_effect(plan["plan_id"], actor=actor) == leader_result
        else:
            assert connection.execute("SELECT count(*) n FROM reconforge.inventory_movements WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0


def test_legacy_fifo_consumption_and_restore_preserve_receipt_history_but_refuse_unused_inverse(receipt_runtime: ReceiptRuntime):
    from reconforge.infrastructure.postgres_inventory_valuation_reversal import (
        PostgresInventoryValuationReversalRepository,
    )
    runtime = receipt_runtime
    plan, review = prepare_and_review(runtime)
    with runtime.actor("poster") as (_, repository, actor):
        original_effect = repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=actor)
    with runtime.actor("maker") as (_, repository, actor):
        delivery = repository.inventory.create_movement(movement_number="LATER-DELIVERY", movement_type="Delivery", organization_code="ORG", entity_code="ENTITY",
            period_id="period", movement_date="2026-10-04", description="Ordinary later consumption", lines=[{"item_code": "ITEM", "quantity": "1", "from_location": "MAIN/STOCK"}], workspace="work", actor_label=actor.username)
    with runtime.actor("checker") as (_, repository, actor):
        repository.inventory.post_movement(delivery["id"], reason="Independent physical review", actor_label=actor.username)
    with runtime.actor("maker") as (connection, _, actor):
        document = PostgresInventoryValuationRepository(connection, runtime.tenant).create_document(valuation_number="LATER-ISSUE-VALUATION", movement_id=delivery["id"], policy_code="FIFO", actor_label=actor.username)
    with runtime.actor("checker") as (connection, repository, actor):
        approved = PostgresInventoryValuationRepository(connection, runtime.tenant).approve_document(document["id"], reason="Independent cost review", actor_label=actor.username)
        assert approved["total_value"] == "12.00"
        assert repository.get_effect(plan["plan_id"], actor=actor) == original_effect
    with runtime.actor("maker") as (_, repository, actor):
        with pytest.raises(FinancePostingError, match="unused"):
            repository.prepare_reversal(ReceiptReversalPreparation(original_plan_id=plan["plan_id"], reversal_number="BAD-INVERSE", posting_date="2026-10-05", period_id="period", reason="Cannot reverse consumed source"), command_id="bad-inverse", actor=actor)
        returned = repository.inventory.create_movement(movement_number="LATER-RETURN", movement_type="Receipt", organization_code="ORG", entity_code="ENTITY",
            period_id="period", movement_date="2026-10-05", description="Ordinary return of later issue", lines=[{"item_code": "ITEM", "quantity": "1", "to_location": "MAIN/STOCK"}], workspace="work", actor_label=actor.username)
    with runtime.actor("checker") as (_, repository, actor):
        repository.inventory.post_movement(returned["id"], reason="Independent return review", actor_label=actor.username)
    with runtime.actor("maker") as (connection, _, actor):
        reversal = PostgresInventoryValuationReversalRepository(connection, runtime.tenant).create_reversal(reversal_number="LATER-ISSUE-REVERSE", original_valuation_document_id=document["id"], reversal_movement_id=returned["id"], actor_label=actor.username)
    with runtime.actor("checker") as (connection, repository, actor):
        PostgresInventoryValuationReversalRepository(connection, runtime.tenant).approve_reversal(reversal["id"], reason="Independent restore of issue", actor_label=actor.username)
        assert repository.get_effect(plan["plan_id"], actor=actor) == original_effect
        assert connection.execute("SELECT remaining_quantity_scaled FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND id=%s", (runtime.tenant, original_effect["cost_layer_id"])).fetchone()["remaining_quantity_scaled"] == 10
    with runtime.actor("maker") as (_, repository, actor), pytest.raises(FinancePostingError, match="history"):
        repository.prepare_reversal(ReceiptReversalPreparation(original_plan_id=plan["plan_id"], reversal_number="STILL-BAD", posting_date="2026-10-06", period_id="period", reason="History remains after restore"), command_id="still-bad", actor=actor)


def test_metadata_delete_fk_lock_conflict_has_bounded_complete_or_rollback_outcome(receipt_runtime: ReceiptRuntime, monkeypatch):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    import psycopg

    from reconforge.infrastructure.postgres_inventory_receipt_posting import _ReceiptFinanceParticipant

    runtime = receipt_runtime
    plan, review = prepare_and_review(runtime)
    admitted, continue_post, deleting = threading.Event(), threading.Event(), threading.Event()
    deletion_pid = []
    materialize = _ReceiptFinanceParticipant.materialize_draft
    def hold_finance(self, *args, **kwargs):
        admitted.set()
        assert continue_post.wait(15)
        return materialize(self, *args, **kwargs)
    monkeypatch.setattr(_ReceiptFinanceParticipant, "materialize_draft", hold_finance)
    def post():
        with runtime.actor("poster") as (_, repository, actor):
            return repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=actor)
    def remove():
        with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work", organization_id="org") as connection:
            deletion_pid.append(connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"])
            deleting.set()
            connection.execute("DELETE FROM reconforge.finance_accounts WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["mapping"]["inventory_account_id"]))
    with ThreadPoolExecutor(max_workers=2) as pool:
        posting = pool.submit(post)
        try:
            assert admitted.wait(15)
            deletion = pool.submit(remove)
            assert deleting.wait(15)
            observed = False
            with psycopg.connect(runtime.admin_dsn, autocommit=True) as control:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    row = control.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", (deletion_pid[0],)).fetchone()
                    if row and row[0] == "Lock":
                        observed = True
                        break
                    time.sleep(0.025)
            assert observed
        finally:
            continue_post.set()
        errors = []
        try:
            posting.result(timeout=15)
        except (psycopg.Error, FinancePostingError) as error:
            errors.append(error)
        with pytest.raises(psycopg.Error) as denied:
            deletion.result(timeout=15)
        assert denied.value.sqlstate in {"23503", "23514", "40P01", "40001"}
        assert len(errors) <= 1
    monkeypatch.setattr(_ReceiptFinanceParticipant, "materialize_draft", materialize)
    with runtime.actor("poster") as (connection, repository, actor):
        # Any deadlock victim retries the same immutable command; no partial source survives.
        count = connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"]
        assert count in (0, 1)
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_movements WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == count
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_receipt_links WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == count
        result = repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=actor)
        assert repository.get_effect(plan["plan_id"], actor=actor) == result


def test_retained_inverse_read_verifies_original_physical_backing(receipt_runtime: ReceiptRuntime):
    import psycopg
    runtime = receipt_runtime
    plan, review = prepare_and_review(runtime)
    with runtime.actor("poster") as (_, repository, actor):
        repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=actor)
    with runtime.actor("maker") as (_, repository, actor):
        inverse = repository.prepare_reversal(ReceiptReversalPreparation(original_plan_id=plan["plan_id"], reversal_number="INVERSE", posting_date="2026-10-04", period_id="period", reason="Full inverse"), command_id="inverse-prepare", actor=actor)
    with runtime.actor("checker") as (_, repository, actor):
        inverse_review = repository.review(inverse["plan_id"], command_id="inverse-review", expected_plan_digest=inverse["plan_digest"], reason="Review", actor=actor)
        repository.commit(inverse["plan_id"], command_id="inverse-commit", expected_review_digest=inverse_review["review_digest"], reason="Publish inverse", actor=actor)
    # Simulate corrupted retained/restored content as the isolated database owner;
    # this does not claim prevention of administrator trigger disabling.
    with psycopg.connect(runtime.admin_dsn) as admin:
        admin.execute("ALTER TABLE reconforge.inventory_movements DISABLE TRIGGER ALL")
        admin.execute("UPDATE reconforge.inventory_movements SET description='corrupt retained original' WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["artifacts"]["movement_id"]))
        admin.execute("ALTER TABLE reconforge.inventory_movements ENABLE TRIGGER ALL")
    with runtime.actor("checker") as (_, repository, actor):
        for identifier in (plan["plan_id"], inverse["plan_id"]):
            with pytest.raises(FinancePostingError, match="backing disagrees"):
                repository.get_effect(identifier, actor=actor)


def changed_registry(runtime: ReceiptRuntime, plan: Any) -> tuple[str, str, str]:
    from reconforge.utils.money import CurrencyRegistryContext
    with runtime.actor("maker") as (connection, _, _actor):
        payload = connection.execute("SELECT snapshot_json FROM reconforge.currency_registry_snapshots WHERE tenant_id=%s AND registry_digest=%s",
                                     (runtime.tenant, plan["currency_policy"]["currency_registry_digest"])).fetchone()["snapshot_json"]
    snapshot = dict(payload) if isinstance(payload, dict) else json.loads(payload)
    snapshot["source"] = "Synthetic source-only registry change"
    snapshot.pop("digest", None)
    context = CurrencyRegistryContext.from_snapshot(snapshot)
    return context.registry_manifest.registry_version, context.registry_manifest.digest, json.dumps(context.snapshot())


def bind_registry(connection: Any, tenant: str, changed: tuple[str, str, str]) -> None:
    version, digest, payload = changed
    connection.execute("INSERT INTO reconforge.currency_registry_snapshots(tenant_id,registry_digest,registry_version,snapshot_json,captured_by) VALUES(%s,%s,%s,%s::jsonb,'synthetic') ON CONFLICT DO NOTHING",
                       (tenant, digest, version, payload))
    connection.execute("INSERT INTO reconforge.currency_registry_bindings(tenant_id,workspace_id,registry_version,registry_digest,bound_by) VALUES(%s,'work',%s,%s,'synthetic') ON CONFLICT(tenant_id,workspace_id) DO UPDATE SET registry_digest=excluded.registry_digest,registry_version=excluded.registry_version",
                       (tenant, version, digest))


def test_registry_rebind_refuses_pending_actions_but_preserves_posted_history(receipt_runtime: ReceiptRuntime):
    from dataclasses import replace
    runtime = receipt_runtime
    plan, review = prepare_and_review(runtime)
    with runtime.actor("poster") as (_, repository, actor):
        effect = repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=actor)
    with runtime.actor("maker") as (_, repository, actor):
        future = repository.prepare_receipt(replace(request("FUTURE"), posting_date="2026-10-04"), command_id="future-prepare", actor=actor)
        pending = repository.prepare_receipt(replace(request("PENDING"), posting_date="2026-10-05"), command_id="pending-prepare", actor=actor)
    with runtime.actor("checker") as (_, repository, actor):
        future_review = repository.review(future["plan_id"], command_id="future-review", expected_plan_digest=future["plan_digest"], reason="Future review", actor=actor)
    changed = changed_registry(runtime, plan)
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work") as connection:
        bind_registry(connection, runtime.tenant, changed)
    with runtime.actor("poster") as (connection, repository, actor):
        before = backing_digest(connection, runtime.tenant)
        assert repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=actor) == effect
        assert repository.get_effect(plan["plan_id"], actor=actor) == effect
        assert repository.prepare_receipt(request(), command_id="prepare-1", actor=actor) == plan
        with pytest.raises(FinancePostingError, match="monetary policy changed"):
            repository.commit(future["plan_id"], command_id="future-commit", expected_review_digest=future_review["review_digest"], reason="Publish", actor=actor)
        with pytest.raises(FinancePostingError, match="monetary policy changed"):
            repository.review(pending["plan_id"], command_id="pending-review", expected_plan_digest=pending["plan_digest"], reason="Review", actor=actor)
        assert backing_digest(connection, runtime.tenant) == before
    with runtime.actor("maker") as (_, repository, actor):
        current = repository.prepare_receipt(replace(request("CURRENT"), posting_date="2026-10-06"), command_id="current-prepare", actor=actor)
        assert current["currency_policy"]["currency_registry_digest"] == changed[1]


def test_existing_consumable_item_has_complete_reviewed_receipt(receipt_runtime: ReceiptRuntime):
    runtime = receipt_runtime
    with runtime.actor("maker") as (connection, _, _actor):
        connection.execute("UPDATE reconforge.inventory_items SET item_type='Consumable' WHERE tenant_id=%s", (runtime.tenant,))
    plan, review = prepare_and_review(runtime)
    with runtime.actor("poster") as (connection, repository, actor):
        effect = repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=actor)
        assert effect["source_kind"] == "InventoryReceipt"
        assert [line["debit_minor"] for line in effect["finance_effect"]["snapshot"]["lines"]] == [12000, 0]
        assert dict(connection.execute("SELECT remaining_quantity_scaled,remaining_value_minor FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND id=%s", (runtime.tenant, effect["cost_layer_id"])).fetchone()) == {"remaining_quantity_scaled": 10, "remaining_value_minor": 12000}


@pytest.mark.parametrize("receipt_first", [True, False])
def test_first_registry_binding_and_receipt_admission_serialize(receipt_runtime: ReceiptRuntime, monkeypatch, receipt_first):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    import psycopg
    runtime = receipt_runtime
    plan, review = prepare_and_review(runtime)
    changed = changed_registry(runtime, plan)
    held, release, follower_started = threading.Event(), threading.Event(), threading.Event()
    follower_pid = []
    def post():
        with runtime.actor("poster") as (connection, repository, actor):
            if receipt_first:
                admit = repository._admit
                def held_admission(*args, **kwargs):
                    admit(*args, **kwargs)
                    held.set()
                    assert release.wait(15)
                monkeypatch.setattr(repository, "_admit", held_admission)
            else:
                follower_pid.append(connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"])
                follower_started.set()
            return repository.commit(plan["plan_id"], command_id="commit-1", expected_review_digest=review["review_digest"], reason="Publish", actor=actor)
    def rebind():
        with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work") as connection:
            if receipt_first:
                follower_pid.append(connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"])
                follower_started.set()
            bind_registry(connection, runtime.tenant, changed)
            if not receipt_first:
                held.set()
                assert release.wait(15)
    with ThreadPoolExecutor(max_workers=2) as pool:
        leader = pool.submit(post if receipt_first else rebind)
        try:
            assert held.wait(15)
            follower = pool.submit(rebind if receipt_first else post)
            assert follower_started.wait(15)
            observed = False
            with psycopg.connect(runtime.admin_dsn, autocommit=True) as control:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    row = control.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", (follower_pid[0],)).fetchone()
                    if row and row[0] == "Lock":
                        observed = True
                        break
                    time.sleep(0.025)
            assert observed
        finally:
            release.set()
        effect = leader.result(timeout=15)
        if receipt_first:
            follower.result(timeout=15)
        else:
            with pytest.raises(FinancePostingError, match="monetary policy changed"):
                follower.result(timeout=15)
    with runtime.actor("checker") as (connection, repository, actor):
        count = connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"]
        assert count == (1 if receipt_first else 0)
        if receipt_first:
            assert repository.get_effect(plan["plan_id"], actor=actor) == effect
        else:
            assert connection.execute("SELECT count(*) n FROM reconforge.inventory_receipt_links WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
