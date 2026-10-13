"""Actual non-owner source voucher tests; independent native evidence is exported."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_accrual_deferral import PostgresAccrualDeferralRepository
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_master_data import PostgresMasterDataRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from reconforge.platform.common import ServerPrincipal, server_principal_context
from tests.accrual_deferral_fixture import preparation as pure_preparation
from tests.test_postgres_inventory_receipt_posting import (
    ReceiptRuntime,
    create_receipt_runtime,
    pytestmark,
    receipt_database,
)

__all__ = ["pytestmark", "receipt_database"]


@dataclass
class ScheduleRuntime:
    base: ReceiptRuntime

    @contextmanager
    def actor(self, name: str) -> Iterator[tuple[Any, PostgresAccrualDeferralRepository, PostingActor]]:
        boundary = PostgresTenantBoundary(self.base.factory)
        with boundary.transaction(self.base.tenant) as connection:
            identity = PostgresIdentityRepository(connection)
            user = identity.authenticate_user(tenant_id=self.base.tenant, username=name, password=self.base.password)
            assert user is not None
            permissions = identity.user_permissions(tenant_id=self.base.tenant, user_id=user.id)
        with boundary.transaction(self.base.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity") as connection:
            principal = ServerPrincipal(user=user, permissions=permissions, step_up_active=True,
                authorized_tenant_ids=frozenset({self.base.tenant}), authorized_workspace_ids=frozenset({"work"}),
                authorized_organization_ids=frozenset({"org"}), authorized_legal_entity_ids=frozenset({"entity"}))
            with server_principal_context(principal):
                yield connection, PostgresAccrualDeferralRepository(connection, self.base.tenant), PostingActor(
                    user.id, user.username, permissions, step_up_active=True)


@pytest.fixture(scope="module")
def accrual_deferral_database(receipt_database: tuple[str, str]) -> tuple[str, str]:
    import psycopg
    from psycopg import sql

    from reconforge.infrastructure.postgres_accrual_deferral_schema import DOWNGRADE_SQL, UPGRADE_SQL
    from reconforge.infrastructure.postgres_accrual_deferral_source_ownership import DOWNGRADE_SQL as DIRECTORY_DOWN
    from reconforge.infrastructure.postgres_accrual_deferral_source_ownership import UPGRADE_SQL as DIRECTORY_SQL

    with psycopg.connect(receipt_database[0]) as admin:
        if admin.execute("SELECT to_regclass('reconforge.accrual_deferral_sources')").fetchone()[0] is None:
            baseline = logical_catalog(admin)
            admin.execute(UPGRADE_SQL)
            admin.execute(DIRECTORY_SQL)
            installed = logical_catalog(admin)
            admin.execute(DIRECTORY_DOWN)
            admin.execute(DOWNGRADE_SQL)
            assert logical_catalog(admin) == baseline
            admin.execute(UPGRADE_SQL)
            admin.execute(DIRECTORY_SQL)
            assert logical_catalog(admin) == installed
            write_catalog({"schema_version": "ad1-development-empty-catalog-roundtrip-v1", "baseline": baseline, "installed": installed,
                "empty_down_matches_baseline": True, "empty_reup_matches_installed": True})
        if admin.execute("SELECT to_regprocedure('reconforge.financial_source_ad1_claim_close(text,text)')").fetchone()[0] is None:
            admin.execute(DIRECTORY_SQL)
        # Current head is preserved; manual additive installation is a
        # development proof until ordered revision141 is independently run.
        ordinary = psycopg.conninfo.conninfo_to_dict(receipt_database[1])["user"]
        admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(sql.Identifier(ordinary)))
    return receipt_database


def logical_catalog(connection: Any) -> dict[str, Any]:
    return {
        "columns": connection.execute("""SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attgenerated,
            pg_get_expr(d.adbin,d.adrelid),c.relrowsecurity,c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
            WHERE n.nspname='reconforge' AND c.relkind IN('r','p') ORDER BY c.relname,a.attname""").fetchall(),
        "constraints": connection.execute("""SELECT r.relname,c.conname,pg_get_constraintdef(c.oid) FROM pg_constraint c
            JOIN pg_class r ON r.oid=c.conrelid JOIN pg_namespace n ON n.oid=r.relnamespace WHERE n.nspname='reconforge' ORDER BY r.relname,c.conname""").fetchall(),
        "indexes": connection.execute("SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='reconforge' ORDER BY tablename,indexname").fetchall(),
        "policies": connection.execute("SELECT tablename,policyname,permissive,roles,cmd,qual,with_check FROM pg_policies WHERE schemaname='reconforge' ORDER BY tablename,policyname").fetchall(),
        "functions": connection.execute("SELECT p.proname,pg_get_function_identity_arguments(p.oid),pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='reconforge' AND p.prokind='f' ORDER BY p.proname,pg_get_function_identity_arguments(p.oid)").fetchall(),
        "triggers": connection.execute("SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='reconforge' AND NOT t.tgisinternal ORDER BY c.relname,t.tgname").fetchall(),
    }


def write_catalog(value: dict[str, Any]) -> None:
    import json
    from pathlib import Path
    from uuid import uuid4

    directory = Path(__file__).resolve().parents[1] / "output/m2-accrual-deferral"
    directory.mkdir(parents=True, exist_ok=True)
    # Native logical catalog custody has a separate artifact contract; it is
    # not a bounded financial posting snapshot or application payload.
    with (directory / ("catalog-roundtrip-" + uuid4().hex + ".json")).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


@pytest.fixture
def runtime(accrual_deferral_database: tuple[str, str]) -> ScheduleRuntime:
    base = create_receipt_runtime(accrual_deferral_database)
    return configure_runtime(base)


def configure_runtime(base: ReceiptRuntime) -> ScheduleRuntime:
    with PostgresTenantBoundary(base.factory).transaction(base.tenant) as connection:
        # Source date and first release share an explicit actual October period;
        # later tranches remain distinct native fiscal periods.
        for identifier, name, first, last, year, number in (
            ("p2", "2026-11", "2026-11-01", "2026-11-30", 2026, 11),
            ("p3", "2026-12", "2026-12-01", "2026-12-31", 2026, 12),
            ("p4", "2027-01", "2027-01-01", "2027-01-31", 2027, 1),
        ):
            connection.execute("""INSERT INTO reconforge.fiscal_periods(tenant_id,id,name,start_date,end_date,fiscal_year,period_number,application_workspace_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,'work')""", (base.tenant, identifier, name, first, last, year, number))
            connection.execute("INSERT INTO reconforge.master_data_workspace_periods(tenant_id,workspace_id,period_id) VALUES(%s,'work',%s)", (base.tenant, identifier))
        finance = PostgresFinanceCoreRepository(connection, base.tenant)
        for account, kind in (("PREPAID", "Asset"), ("EXPENSE", "Expense"), ("ACCRUAL", "Liability"), ("CASH", "Asset")):
            finance.upsert_account(account_code=account, name=account, account_type=kind, chart_code="DEFAULT", workspace="work")
        finance.upsert_journal(journal_code="AD1_NATIVE", name="Native voucher schedule", organization_code="ORG", currency_code="USD", workspace="work")
        identity = PostgresIdentityRepository(connection)
        for permission in ("finance_core.read", "master_data.manage", "accrual_deferral.read", "accrual_deferral.prepare", "accrual_deferral.review", "accrual_deferral.post"):
            identity.create_permission(tenant_id=base.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=base.tenant, role_name="receipt-operator", permission_name=permission)
        authority = PostgresScopeAuthorityRepository(connection)
        for actor in ("maker", "checker", "poster"):
            for kind, identifier in (("workspace", "work"), ("organization", "org"), ("legal_entity", "entity")):
                existing = connection.execute("""SELECT 1 FROM reconforge.principal_scope_grants WHERE tenant_id=%s
                    AND principal_type='user' AND principal_id=%s AND scope_type=%s AND scope_id=%s AND revoked_at IS NULL""",
                    (base.tenant, actor, kind, identifier)).fetchone()
                if existing is None:
                    authority.grant(tenant_id=base.tenant, grant_id="ad1-" + actor + identifier, principal_type="user",
                        principal_id=actor, scope_type=kind, scope_id=identifier, actor_id=actor)
        PostgresMasterDataRepository(connection).bind_currency_registry(tenant_id=base.tenant, workspace="work", actor_id="maker")
    return ScheduleRuntime(base)


def preparation(mode="new_prepaid_voucher", reference="AD1-VOUCHER-1"):
    request = pure_preparation(mode)
    return replace(request, reference=reference, period_id="period", tranches=tuple(
        replace(item, period_id="period" if item.id == "T1" else item.period_id) for item in request.tranches))


def publish(runtime: ScheduleRuntime, plan: dict[str, Any], suffix: str) -> dict[str, Any]:
    with runtime.actor("checker") as (_, repository, actor):
        repository.review(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Reviewed exact immutable original source", command_id="review-" + suffix, actor=actor)
    with runtime.actor("poster") as (_, repository, actor):
        return repository.post(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Third human native publication", command_id="post-" + suffix, actor=actor)


def native_balances(connection: Any, tenant: str) -> dict[str, int]:
    rows = connection.execute("""SELECT a.account_code,sum(l.debit_minor-l.credit_minor) AS amount FROM reconforge.finance_entry_lines l
        JOIN reconforge.finance_posting_effects f ON f.tenant_id=l.tenant_id AND f.entry_id=l.entry_id
        JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id
        WHERE l.tenant_id=%s GROUP BY a.account_code""", (tenant,)).fetchall()
    return {row["account_code"]: int(row["amount"]) for row in rows}


def test_three_human_cash_voucher_three_tranches_and_exact_original_inverse(runtime: ScheduleRuntime) -> None:
    with runtime.actor("maker") as (_, repository, actor):
        prepared = repository.prepare_source(preparation(), command_id="prepare-source", actor=actor)
    original = publish(runtime, prepared, "source")
    assert original["posting_effect_id"] and original["equation"]["cash_changed_minor"] == -10001
    with runtime.actor("maker") as (_, repository, actor):
        assert repository.prepare_source(preparation(), command_id="prepare-source", actor=actor) == prepared
    posted = []
    for tranche in ("T1", "T2", "T3"):
        with runtime.actor("maker") as (_, repository, actor):
            plan = repository.prepare_tranche(original["source_id"], tranche_id=tranche, command_id="prepare-" + tranche, actor=actor)
        posted.append(publish(runtime, plan, tranche))
    with runtime.actor("maker") as (_, repository, actor):
        inverse = repository.prepare_reversal(original["source_id"], original_plan_id=posted[1]["id"], period_id="p3",
            posting_date="2026-12-30", reason="Exact original second service tranche correction", command_id="prepare-inverse", actor=actor)
    reversed_plan = publish(runtime, inverse, "inverse")
    assert reversed_plan["equation"]["original_posting_effect_id"] == posted[1]["posting_effect_id"]
    with runtime.actor("maker") as (_, repository, actor):
        replacement = repository.prepare_tranche(original["source_id"], tranche_id="T2", command_id="prepare-replacement", actor=actor)
    publish(runtime, replacement, "replacement")
    with runtime.actor("maker") as (connection, repository, actor):
        assert entity_selectors(connection) == ("entity", "entity")
        assert [row["entity_code"] for row in connection.execute("SELECT DISTINCT entity_code FROM reconforge.finance_entries WHERE tenant_id=%s", (runtime.base.tenant,))] == ["ENTITY"]
        assert native_balances(connection, runtime.base.tenant) == {"PREPAID": 0, "EXPENSE": 10001, "CASH": -10001}
        proof = repository.evidence(original["source_id"], actor=actor)
        assert len(proof["native_effects"]) == 6 and all(head["state"] == "Consumed" for head in proof["source"]["claims"])
        flags = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=session_user").fetchone()
        assert not flags["rolsuper"] and not flags["rolbypassrls"]
        write_original(proof, "new-prepaid")


def entity_selectors(connection: Any) -> tuple[str, str]:
    row = connection.execute("SELECT current_setting('app.entity_id',true) AS entity,current_setting('app.legal_entity_id',true) AS legal_entity").fetchone()
    return row["entity"], row["legal_entity"]


def test_exact_reference_locks_restore_entity_aliases_on_success_and_errors(runtime: ScheduleRuntime) -> None:
    import psycopg

    with runtime.actor("maker") as (connection, repository, actor):
        request = preparation().payload()
        assert entity_selectors(connection) == ("entity", "entity")
        with pytest.raises(FinancePostingError):
            repository._accounts({**request, "legal_entity_id": "other-entity"}, actor)
        assert entity_selectors(connection) == ("entity", "entity")
        with repository._reference_locks(request, actor):
            assert entity_selectors(connection) == ("", "")
        assert entity_selectors(connection) == ("entity", "entity")
        for error in (RuntimeError, psycopg.errors.DivisionByZero):
            with pytest.raises(error), repository._reference_locks(request, actor):
                if error is RuntimeError:
                    raise RuntimeError("Synthetic metadata lock failure")
                connection.execute("SELECT 1/0")
            assert entity_selectors(connection) == ("entity", "entity")
            repository._authorize(actor, "prepare", request, lock=True)
        assert len(repository._accounts(request, actor)) == 4
        assert entity_selectors(connection) == ("entity", "entity")
        with pytest.raises(FinancePostingError, match="Four captured"):
            repository._accounts({**request, "organization_code": "WRONG_ORGANIZATION"}, actor)
        assert entity_selectors(connection) == ("entity", "entity")


def write_original(proof: dict[str, Any], name: str) -> None:
    from pathlib import Path
    from uuid import uuid4

    from reconforge.domain.finance_posting import canonical_json

    directory = Path(__file__).resolve().parents[1] / "output/m2-accrual-deferral"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ("native-" + name + "-" + uuid4().hex + ".json")).open("x", encoding="utf-8") as handle:
        handle.write(canonical_json(proof))


def test_cash_source_separation_and_whole_transaction_rollback_on_same_actor(runtime: ScheduleRuntime) -> None:
    with runtime.actor("maker") as (_, repository, actor):
        plan = repository.prepare_source(preparation(), command_id="prepare-one", actor=actor)
    with pytest.raises(FinancePostingError, match="three distinct"), runtime.actor("maker") as (_, repository, actor):
        repository.review(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Self review refused", command_id="same-actor", actor=actor)
    with runtime.actor("maker") as (connection, _, _):
        assert native_balances(connection, runtime.base.tenant) == {}
        assert connection.execute("SELECT count(*) AS n FROM reconforge.accrual_deferral_commands WHERE tenant_id=%s", (runtime.base.tenant,)).fetchone()["n"] == 1


def paid_original(runtime: ScheduleRuntime, debit: str = "EXPENSE", number: str = "PAID-ORIGINAL-1", *, dimensions: bool = False) -> dict[str, Any]:
    if dimensions:
        with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant, workspace_id="work", organization_id="org") as connection:
            finance = PostgresFinanceCoreRepository(connection, runtime.base.tenant)
            for dimension, kind, value in (("PROJECT", "Project", "SERVICE"), ("BRANCH", "Custom", "MAIN")):
                finance.upsert_dimension(dimension_code=dimension, name=dimension, workspace="work", organization_code="ORG", dimension_type=kind)
                finance.upsert_dimension_value(dimension_code=dimension, value_code=value, name=value, workspace="work")
    with runtime.actor("maker") as (_, repository, actor):
        draft = repository.owner.finance.create_entry(entry_number=number, organization_code="ORG", entity_code="ENTITY",
            journal_code="AD1_NATIVE", period_id="period", posting_date="2026-10-01", workspace="work",
            description="Approved original external paid service", external_reference="SUPPLIER-PAID-" + number, actor_label=actor.username,
            lines=[{"account_code": debit, "debit": "100.01", "dimensions": {"PROJECT": "SERVICE"} if dimensions else {}},
                {"account_code": "CASH", "credit": "100.01", "dimensions": {"BRANCH": "MAIN"} if dimensions else {}}])
    with runtime.actor("checker") as (_, repository, actor):
        repository.owner.finance.validate_entry(draft["id"], reason="Independent original paid voucher review", actor_label=actor.username)
        preview = repository.owner.posting.preview(draft["id"], actor=actor)
    with runtime.actor("poster") as (_, repository, actor):
        return repository.owner.posting.post(draft["id"], command_id="paid-original-" + number,
            expected_validation_digest=preview["validation_digest"], reason="Third human original paid voucher", actor=actor)


@pytest.mark.parametrize("mode,debit", (("attach_paid_expense", "EXPENSE"), ("attach_prepaid_voucher", "PREPAID")))
def test_exact_paid_original_membership_and_three_tranches_never_charge_cash_twice(runtime: ScheduleRuntime, mode: str, debit: str) -> None:
    original = paid_original(runtime, debit)
    request = replace(preparation(mode), original_effect_id=original["id"])
    with runtime.actor("maker") as (_, repository, actor):
        plan = repository.prepare_source(request, command_id="attach-original", actor=actor)
    source = publish(runtime, plan, "attach-original")
    assert source["equation"]["cash_changed_minor"] == 0
    assert bool(source["posting_effect_id"]) == (mode == "attach_paid_expense")
    with pytest.raises(FinancePostingError), runtime.actor("maker") as (_, repository, actor):
        repository.owner.posting.prepare_reversal(original["id"], command_id="original-inverse-refused", entry_number="ORDINARY-INVERSE",
            period_id="p2", posting_date="2026-11-01", reason="Active ownership must refuse generic inverse", actor=actor)
    for tranche in ("T1", "T2", "T3"):
        with runtime.actor("maker") as (_, repository, actor):
            selected = repository.prepare_tranche(source["source_id"], tranche_id=tranche, command_id="attach-" + tranche, actor=actor)
        publish(runtime, selected, "attach-" + tranche)
    with runtime.actor("maker") as (connection, repository, actor):
        assert native_balances(connection, runtime.base.tenant) == {"PREPAID": 0, "EXPENSE": 10001, "CASH": -10001}
        assert repository.owner.posting._get_effect(original["id"]) == original
        proof = repository.evidence(source["source_id"], actor=actor)
        assert proof["original_claims"][0]["state"] == "Consumed"
        assert len(proof["native_effects"]) == (5 if mode == "attach_paid_expense" else 4)
        write_original(proof, mode)


@pytest.mark.parametrize("mode,debit", (("attach_paid_expense", "EXPENSE"), ("attach_prepaid_voucher", "PREPAID")))
def test_paid_original_actual_project_and_cash_branch_dimensions_remain_exact(runtime: ScheduleRuntime, mode: str, debit: str) -> None:
    original = paid_original(runtime, debit, dimensions=True)
    with runtime.actor("maker") as (_, repository, actor):
        plan = repository.prepare_source(replace(preparation(mode), original_effect_id=original["id"]), command_id="dimension-source", actor=actor)
    source = publish(runtime, plan, "dimension-source")
    for tranche in ("T1", "T2", "T3"):
        with runtime.actor("maker") as (_, repository, actor):
            prepared = repository.prepare_tranche(source["source_id"], tranche_id=tranche, command_id="dimension-" + tranche, actor=actor)
        publish(runtime, prepared, "dimension-" + tranche)
    with runtime.actor("maker") as (connection, repository, actor):
        proof = repository.evidence(source["source_id"], actor=actor)
        external = proof["source"]["equation"]["external_original_membership"]
        native_dimensions = {row["dimension_code"]: {row["dimension_id"]: row["value_id"]} for row in connection.execute("""SELECT d.dimension_code,d.id AS dimension_id,v.id AS value_id
            FROM reconforge.finance_dimensions d JOIN reconforge.finance_dimension_values v ON v.tenant_id=d.tenant_id AND v.dimension_id=d.id
            WHERE d.tenant_id=%s AND d.workspace_id='work' AND d.dimension_code IN('PROJECT','BRANCH')""", (runtime.base.tenant,))}
        assert external["basis_dimensions"] == native_dimensions["PROJECT"] == original["snapshot"]["lines"][0]["dimensions"]
        assert external["original_cash_dimensions"] == native_dimensions["BRANCH"] == original["snapshot"]["lines"][1]["dimensions"]
        assert repository.owner.posting._get_effect(original["id"]) == original
        assert native_balances(connection, runtime.base.tenant) == {"PREPAID": 0, "EXPENSE": 10001, "CASH": -10001}
        assert all(line["dimensions"] == native_dimensions["PROJECT"] for member in proof["source"]["plans"] for line in member["equation"]["lines"])
        write_original(proof, mode + "-actual-project-cash-branch")


def test_cancel_unconsumed_attachment_releases_single_directory_before_ordinary_original_inverse(runtime: ScheduleRuntime) -> None:
    original = paid_original(runtime, "PREPAID")
    with runtime.actor("maker") as (_, repository, actor):
        plan = repository.prepare_source(replace(preparation("attach_prepaid_voucher"), original_effect_id=original["id"]), command_id="attach-for-cancel", actor=actor)
    source = publish(runtime, plan, "attach-for-cancel")
    with runtime.actor("maker") as (_, repository, actor):
        pending = repository.prepare_tranche(source["source_id"], tranche_id="T1", command_id="pending-unposted-tranche", actor=actor)
        cancellation = repository.prepare_cancellation(source["source_id"], reason="Original service cancelled before consumption", command_id="cancel-source", actor=actor)
    cancelled = publish(runtime, cancellation, "cancel-source")
    assert cancelled["posting_effect_id"] is None
    with pytest.raises(FinancePostingError), runtime.actor("checker") as (_, repository, actor):
        repository.review(pending["id"], expected_plan_digest=pending["plan_digest"], reason="Cancelled original cannot resume", command_id="cancelled-review", actor=actor)
    with runtime.actor("maker") as (_, repository, actor):
        proof = repository.evidence(source["source_id"], actor=actor)
        assert proof["source"]["cancelled"] and proof["original_claims"][0]["state"] == "Released"
        assert len(proof["financial_directory_releases"]) == 1
        write_original(proof, "cancelled-attachment")
        inverse = repository.owner.posting.prepare_reversal(original["id"], command_id="released-original-inverse", entry_number="ORDINARY-RELEASED-INVERSE",
            period_id="p2", posting_date="2026-11-01", reason="Governed original inverse after exact release", actor=actor)
    with runtime.actor("checker") as (_, repository, actor):
        repository.owner.finance.validate_entry(inverse["entry_id"], reason="Independent released original inverse", actor_label=actor.username)
        preview = repository.owner.posting.preview(inverse["entry_id"], actor=actor)
    with runtime.actor("poster") as (connection, repository, actor):
        repository.owner.posting.post(inverse["entry_id"], command_id="released-original-inverse-post", expected_validation_digest=preview["validation_digest"],
            reason="Third human exact original inverse after cancellation", actor=actor)
        assert all(amount == 0 for amount in native_balances(connection, runtime.base.tenant).values())


def test_accrual_estimate_requires_each_next_period_exact_inverse_and_changes_no_cash(runtime: ScheduleRuntime) -> None:
    with runtime.actor("maker") as (_, repository, actor):
        plan = repository.prepare_source(preparation("expense_accrual"), command_id="accrual-estimate", actor=actor)
    source = publish(runtime, plan, "accrual-estimate")
    assert source["posting_effect_id"] is None
    for index, tranche in enumerate(("T1", "T2", "T3"), 2):
        with runtime.actor("maker") as (_, repository, actor):
            prepared = repository.prepare_tranche(source["source_id"], tranche_id=tranche, command_id="accrue-" + tranche, actor=actor)
        posted = publish(runtime, prepared, "accrue-" + tranche)
        with runtime.actor("maker") as (_, repository, actor):
            inverse = repository.prepare_reversal(source["source_id"], original_plan_id=posted["id"], period_id="p" + str(index),
                posting_date=("2026-11-01", "2026-12-01", "2027-01-01")[index - 2], reason="Exact approved next-period accrual inverse",
                command_id="accrual-inverse-" + tranche, actor=actor)
        publish(runtime, inverse, "accrual-inverse-" + tranche)
    with runtime.actor("maker") as (connection, repository, actor):
        assert native_balances(connection, runtime.base.tenant) == {"EXPENSE": 0, "ACCRUAL": 0}
        proof = repository.evidence(source["source_id"], actor=actor)
        assert len(proof["native_effects"]) == 6
        write_original(proof, "accrual-next-period-inverses")


def test_structural_account_roles_fail_closed_without_private_source_select_and_preserve_ordinary_metadata(runtime: ScheduleRuntime, accrual_deferral_database: tuple[str, str]) -> None:
    import psycopg
    from psycopg import sql

    with runtime.actor("maker") as (_, repository, actor):
        repository.prepare_source(preparation("expense_accrual"), command_id="unposted-role-pins", actor=actor)
    role = psycopg.conninfo.conninfo_to_dict(accrual_deferral_database[1])["user"]
    with psycopg.connect(accrual_deferral_database[0]) as admin:
        admin.execute(sql.SQL("REVOKE SELECT ON reconforge.accrual_deferral_sources,reconforge.accrual_deferral_account_pins FROM {}").format(sql.Identifier(role)))
    try:
        with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant, workspace_id="work", organization_id="org") as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                connection.execute("SELECT * FROM reconforge.accrual_deferral_sources")
            assert connection.execute("UPDATE reconforge.finance_accounts SET name='Reviewed metadata name',description='Ordinary reference metadata',active=false WHERE tenant_id=%s AND account_code='ACCRUAL'", (runtime.base.tenant,)).rowcount == 1
            with pytest.raises(psycopg.errors.ForeignKeyViolation), connection.transaction():
                connection.execute("UPDATE reconforge.finance_accounts SET account_type='Expense' WHERE tenant_id=%s AND account_code='ACCRUAL'", (runtime.base.tenant,))
            with pytest.raises(psycopg.errors.ForeignKeyViolation), connection.transaction():
                connection.execute("DELETE FROM reconforge.finance_accounts WHERE tenant_id=%s AND account_code='ACCRUAL'", (runtime.base.tenant,))
            finance = PostgresFinanceCoreRepository(connection, runtime.base.tenant)
            finance.upsert_account(account_code="UNREFERENCED", name="Ordinary unused reference", account_type="Expense", chart_code="DEFAULT", workspace="work")
            assert connection.execute("DELETE FROM reconforge.finance_accounts WHERE tenant_id=%s AND account_code='UNREFERENCED'", (runtime.base.tenant,)).rowcount == 1
    finally:
        with psycopg.connect(accrual_deferral_database[0]) as admin:
            admin.execute(sql.SQL("GRANT SELECT ON reconforge.accrual_deferral_sources,reconforge.accrual_deferral_account_pins TO {}").format(sql.Identifier(role)))
    with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant, workspace_id="work", organization_id="org", legal_entity_id="hidden-other-entity") as connection:
        assert connection.execute("SELECT count(*) AS n FROM reconforge.accrual_deferral_account_pins WHERE tenant_id=%s", (runtime.base.tenant,)).fetchone()["n"] == 0
