"""Restricted native three-book intercompany cycles, atomicity and current authority."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.financial_reporting import AccountClassification, ReportingScope
from reconforge.domain.intercompany_operations import IntercompanyPreparation
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_financial_reporting import PostgresFinancialReportingRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_intercompany_operations import PostgresIntercompanyOperationsRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from reconforge.platform.common import ServerPrincipal, server_principal_context
from tests.test_postgres_inventory_receipt_posting import (
    ReceiptRuntime,
    create_receipt_runtime,
    pytestmark,
    receipt_database,
)

__all__ = ["receipt_database", "pytestmark"]
ENTITIES = frozenset({"entity", "buyer", "group"})
ACCOUNTS = (("IC_AR", "Asset", "CurrentAsset"), ("IC_AP", "Liability", "CurrentLiability"),
            ("IC_REVENUE", "Income", "Income"), ("IC_EXPENSE", "Expense", "Expense"), ("CASH", "Asset", "CurrentAsset"))


@dataclass
class IntercompanyRuntime:
    base: ReceiptRuntime

    @contextmanager
    def actor(self, name: str, *, entities: frozenset[str] = ENTITIES) -> Iterator[tuple[Any, PostgresIntercompanyOperationsRepository, PostingActor]]:
        boundary = PostgresTenantBoundary(self.base.factory)
        with boundary.transaction(self.base.tenant) as connection:
            identities = PostgresIdentityRepository(connection)
            user = identities.authenticate_user(tenant_id=self.base.tenant, username=name, password=self.base.password)
            assert user is not None
            permissions = identities.user_permissions(tenant_id=self.base.tenant, user_id=user.id)
        with boundary.transaction(self.base.tenant, workspace_id="work", organization_id="org") as connection:
            principal = ServerPrincipal(user=user, permissions=permissions, step_up_active=True,
                authorized_tenant_ids=frozenset({self.base.tenant}), authorized_workspace_ids=frozenset({"work"}),
                authorized_organization_ids=frozenset({"org"}), authorized_legal_entity_ids=entities)
            with server_principal_context(principal):
                yield connection, PostgresIntercompanyOperationsRepository(connection, self.base.tenant), PostingActor(
                    user.id, user.username, permissions, step_up_active=True)


@pytest.fixture(scope="module")
def intercompany_database(receipt_database: tuple[str, str]) -> tuple[str, str]:
    import psycopg
    from psycopg import sql

    from reconforge.infrastructure.postgres_intercompany_operations_schema import UPGRADE_SQL

    with psycopg.connect(receipt_database[0]) as admin:
        if admin.execute("SELECT to_regclass('reconforge.intercompany_operation_sources')").fetchone()[0] is None:
            admin.execute(UPGRADE_SQL)
        app_user = psycopg.conninfo.conninfo_to_dict(receipt_database[1])["user"]
        admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(sql.Identifier(app_user)))
    return receipt_database


@pytest.fixture
def runtime(intercompany_database: tuple[str, str]) -> IntercompanyRuntime:
    return seed_intercompany_masters(create_receipt_runtime(intercompany_database))


def seed_intercompany_masters(base: ReceiptRuntime) -> IntercompanyRuntime:
    with PostgresTenantBoundary(base.factory).transaction(base.tenant) as connection:
        for identifier, code in (("buyer", "BUYER"), ("group", "GROUP")):
            connection.execute("INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) VALUES(%s,%s,'org',%s,%s,'USD')",
                               (base.tenant, identifier, code, code))
        finance = PostgresFinanceCoreRepository(connection, base.tenant)
        for code, kind, _ in ACCOUNTS:
            finance.upsert_account(account_code=code, name=code, account_type=kind,
                normal_balance="Credit" if kind in {"Liability", "Income"} else "Debit", chart_code="DEFAULT", workspace="work")
        identities = PostgresIdentityRepository(connection)
        for permission in ("finance_core.read", "intercompany_operations.read", "intercompany_operations.prepare",
                           "intercompany_operations.review", "intercompany_operations.post"):
            identities.create_permission(tenant_id=base.tenant, permission_name=permission)
            identities.grant_permission(tenant_id=base.tenant, role_name="receipt-operator", permission_name=permission)
        authority = PostgresScopeAuthorityRepository(connection)
        for person in ("maker", "checker", "poster"):
            for kind, identifier in (("workspace", "work"), ("organization", "org"), *( ("legal_entity", entity) for entity in sorted(ENTITIES))):
                if connection.execute("SELECT 1 FROM reconforge.principal_scope_grants WHERE tenant_id=%s AND principal_type='user' AND principal_id=%s AND scope_type=%s AND scope_id=%s AND revoked_at IS NULL",
                                      (base.tenant, person, kind, identifier)).fetchone() is None:
                    authority.grant(tenant_id=base.tenant, grant_id=f"ic-{person}-{identifier}", principal_type="user", principal_id=person,
                                    scope_type=kind, scope_id=identifier, actor_id=person)
    return IntercompanyRuntime(base)


def preparation(reference: str = "SERVICE-1") -> IntercompanyPreparation:
    return IntercompanyPreparation("work", "org", "ORG", "entity", "ENTITY", "buyer", "BUYER", "group", "GROUP",
        reference, 10001, "period", "2026-10-03", "STOCK", "IC_AR", "IC_AP", "IC_REVENUE", "IC_EXPENSE", "CASH", "Original service charge")


def publish(rt: IntercompanyRuntime, plan: dict[str, Any], suffix: str) -> dict[str, Any]:
    with rt.actor("checker") as (_, repository, actor):
        repository.review(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Independent review", command_id="review-" + suffix, actor=actor)
    with rt.actor("poster") as (_, repository, actor):
        return repository.post(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Third human publication", command_id="post-" + suffix, actor=actor)


def recognize(rt: IntercompanyRuntime) -> dict[str, Any]:
    with rt.actor("maker") as (_, repository, actor):
        plan = repository.prepare(preparation(), command_id="prepare-original", actor=actor)
    return publish(rt, plan, "original")


def maps(rt: IntercompanyRuntime) -> dict[str, str]:
    result = {}
    for entity in sorted(ENTITIES):
        with rt.actor("maker") as (connection, _, actor):
            mapping = PostgresFinancialReportingRepository(connection, rt.base.tenant).prepare_map(ReportingScope("work", "org", entity),
                name="Explicit " + entity, accounts=[AccountClassification(code, section, code == "CASH") for code, _, section in ACCOUNTS],
                command_id="map-" + entity, actor=actor)
        with rt.actor("checker") as (connection, _, actor):
            PostgresFinancialReportingRepository(connection, rt.base.tenant).review_map(mapping["id"], expected_digest=mapping["map_digest"],
                reason="Reviewed sections", command_id="map-review-" + entity, actor=actor)
        result[entity] = mapping["id"]
    return result


def test_actual_paired_partial_settlement_native_group_elimination_and_drilldown(runtime: IntercompanyRuntime) -> None:
    original = recognize(runtime)
    with runtime.actor("maker") as (_, repository, actor):
        installment = repository.prepare_settlement(original["source_id"], amount_minor=3000, period_id="period", posting_date="2026-10-04",
            reason="Partial cash", command_id="prepare-cash", actor=actor)
    cash = publish(runtime, installment, "cash")
    with runtime.actor("maker") as (_, repository, actor):
        elimination = repository.prepare_elimination(original["source_id"], period_id="period", posting_date="2026-10-05",
            reason="Explicit reviewed consolidation adjustment", command_id="prepare-group", actor=actor)
    closing = publish(runtime, elimination, "group")
    classifications = maps(runtime)
    with runtime.actor("poster") as (connection, repository, actor):
        proof = repository.evidence(closing["id"], actor=actor)
        report = repository.report(original["source_id"], seller_map_id=classifications["entity"], buyer_map_id=classifications["buyer"],
            adjustment_map_id=classifications["group"], period_id="period", as_of_date="2026-10-05", actor=actor)
        assert len(proof["phases"]) == 3
        assert len({phase["actor_id"] for phase in proof["phases"]}) == 3
        assert all(phase["audit_event_id"] and phase["outbox_event_id"] for phase in proof["phases"])
        assert closing["amount_minor"] == int(Fraction(10001) + Fraction(10001) - Fraction(3000)) == 17002
        assert report["effect_count"] == 5
        assert report["income_statement"] == {"income_minor": 0, "expense_minor": 0, "result_minor": 0}
        assert report["cash_net_movements"] == {"opening_minor": 0, "activity_minor": 0, "closing_minor": 0}
        assert all(row["closing"]["balance_minor"] == 0 for row in report["trial_balance"])
        actual = {line["effect_id"] for row in report["trial_balance"] for line in row["postings"]}
        assert actual == set(original["posting_effect_ids"].values()) | set(cash["posting_effect_ids"].values()) | set(closing["posting_effect_ids"].values())
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.base.tenant,)).fetchone()["n"] == 5
        with pytest.raises(FinancePostingError, match="open original"):
            repository.prepare_settlement(original["source_id"], amount_minor=1, period_id="period", posting_date="2026-10-06", reason="Sealed", command_id="sealed", actor=actor)
    with runtime.actor("maker") as (_, repository, actor):
        assert repository.prepare(preparation(), command_id="prepare-original", actor=actor)["phase"] == 0


def test_direct_sql_half_review_and_public_native_post_or_inverse_refused(runtime: IntercompanyRuntime) -> None:
    with runtime.actor("maker") as (_, repository, actor):
        plan = repository.prepare(preparation(), command_id="prepare-original", actor=actor)
        with pytest.raises(FinancePostingError, match="independent"):
            repository.review(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Self", command_id="self", actor=actor)
    with pytest.raises(Exception, match="Review must seal|Prepared pair"), runtime.actor("checker") as (connection, repository, actor):
        repository.owner.finance.validate_entry(plan["entries"][0]["entry_id"], reason="Detached SQL review", actor_label=actor.username)
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    posted = publish(runtime, plan, "original")
    with runtime.actor("poster") as (_, repository, actor):
        with pytest.raises(FinancePostingError, match="complete|source|owner"):
            repository.owner.posting.post(plan["entries"][0]["entry_id"], command_id="manual", expected_validation_digest=plan["entries"][0]["validation_digest"], reason="Detached", actor=actor)
        with pytest.raises(FinancePostingError, match="reviewed native source inverse"):
            repository.owner.posting.prepare_reversal(next(iter(posted["posting_effect_ids"].values())), command_id="inverse", entry_number="DETACHED",
                period_id="period", posting_date="2026-10-04", reason="Detached", actor=actor)


def test_late_second_effect_failure_rolls_back_whole_pair_and_exact_retry(runtime: IntercompanyRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    with runtime.actor("maker") as (_, repository, actor):
        plan = repository.prepare(preparation(), command_id="prepare-original", actor=actor)
    with runtime.actor("checker") as (_, repository, actor):
        repository.review(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Review", command_id="review-original", actor=actor)
    with runtime.actor("poster") as (connection, repository, actor):
        original = repository.owner.posting.post
        calls = 0
        def fail_second(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("Injected late second native effect failure")
            return original(*args, **kwargs)
        with monkeypatch.context() as scoped:
            scoped.setattr(repository.owner.posting, "post", fail_second)
            with pytest.raises(RuntimeError, match="late second"):
                repository.post(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Publish", command_id="post-original", actor=actor)
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.base.tenant,)).fetchone()["n"] == 0
        assert repository.get_plan(plan["id"], actor=actor)["phase"] == 1
        result = repository.post(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Publish", command_id="post-original", actor=actor)
        assert repository.post(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Publish", command_id="post-original", actor=actor) == result
        assert len(result["posting_effect_ids"]) == 2


def test_concurrent_pending_settlement_serializes_and_same_command_replays(runtime: IntercompanyRuntime) -> None:
    original = recognize(runtime)
    def prepare(command: str) -> Any:
        try:
            with runtime.actor("maker") as (_, repository, actor):
                return repository.prepare_settlement(original["source_id"], amount_minor=7000, period_id="period", posting_date="2026-10-04",
                    reason="Competing cash", command_id=command, actor=actor)
        except FinancePostingError as exc:
            return exc
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(prepare, ("cash-one", "cash-two")))
    assert sum(isinstance(item, dict) for item in results) == 1
    winner = next(item for item in results if isinstance(item, dict))
    posted = publish(runtime, winner, "cash")
    with ThreadPoolExecutor(max_workers=2) as workers:
        replay = list(workers.map(prepare, ("cash-one" if isinstance(results[0], dict) else "cash-two",) * 2))
    assert replay[0] == replay[1] == winner
    assert len(posted["posting_effect_ids"]) == 2


def test_all_three_current_scope_grants_and_retained_group_turnover_are_required(runtime: IntercompanyRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    import reconforge.infrastructure.postgres_operational_finance as authority
    from reconforge.auth.policy import evaluate_principal_access
    original = recognize(runtime)
    with runtime.actor("maker", entities=frozenset({"entity", "group"})) as (_, repository, actor), pytest.raises(FinancePostingError, match="denied"):
        repository.get_source(original["source_id"], actor=actor)
    with runtime.actor("maker") as (_, repository, actor):
        group = repository.prepare_elimination(original["source_id"], period_id="period", posting_date="2026-10-04", reason="Group", command_id="prepare-group", actor=actor)
    assert group["amount_minor"] == 20002
    def ceiling(principal: Any, **context: Any) -> Any:
        return evaluate_principal_access(principal, maximum_amount=Decimal("150"), **context)
    with monkeypatch.context() as scoped, runtime.actor("maker") as (_, repository, actor):
        scoped.setattr(authority, "evaluate_principal_access", ceiling)
        with pytest.raises(FinancePostingError, match="denied"):
            repository.get_plan(group["id"], actor=actor)
        with pytest.raises(FinancePostingError, match="denied"):
            repository.prepare_elimination(original["source_id"], period_id="period", posting_date="2026-10-04", reason="Group", command_id="prepare-group", actor=actor)
    with runtime.actor("maker") as (_, repository, actor):
        assert repository.get_plan(group["id"], actor=actor)["plan_digest"] == group["plan_digest"]


def test_current_group_grant_revocation_after_source_wait_rejects_native_review(runtime: IntercompanyRuntime) -> None:
    from queue import Queue
    from time import monotonic, sleep

    with runtime.actor("maker") as (_, repository, actor):
        plan = repository.prepare(preparation(), command_id="prepare-original", actor=actor)
    pids: Queue[int] = Queue()
    def review() -> Any:
        try:
            with runtime.actor("checker") as (connection, repository, actor):
                pids.put(connection.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"])
                return repository.review(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Wait then admit current group", command_id="blocked-review", actor=actor)
        except FinancePostingError as exc:
            return exc
    blocker = runtime.base.factory.connect()
    blocker.execute("SELECT set_config('app.tenant_id',%s,true),set_config('app.workspace_id','work',true),set_config('app.organization_id','org',true)", (runtime.base.tenant,))
    blocker_pid = blocker.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
    blocker.execute("SELECT id FROM reconforge.intercompany_operation_sources WHERE tenant_id=%s AND id=%s FOR UPDATE", (runtime.base.tenant, plan["source_id"]))
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(review)
            pid = pids.get(timeout=10)
            with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
                deadline = monotonic() + 10
                while blocker_pid not in connection.execute("SELECT pg_blocking_pids(%s) AS pids", (pid,)).fetchone()["pids"]:
                    assert monotonic() < deadline, "Actual source-row lock wait was not established"
                    sleep(.02)
                PostgresScopeAuthorityRepository(connection).revoke(tenant_id=runtime.base.tenant, grant_id="ic-checker-group", actor_id="maker", reason="Withdraw group authority during actual source lock wait")
            blocker.rollback()
            result = future.result(timeout=15)
            assert isinstance(result, FinancePostingError) and result.code == "intercompany_scope_denied"
    finally:
        blocker.rollback()
        blocker.close()
    with runtime.actor("poster") as (connection, repository, actor):
        assert repository.get_plan(plan["id"], actor=actor)["phase"] == 0
        assert connection.execute("SELECT count(*) AS n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.base.tenant,)).fetchone()["n"] == 0
        assert connection.execute("SELECT count(*) AS n FROM reconforge.intercompany_operation_commands WHERE tenant_id=%s AND command_id='blocked-review'", (runtime.base.tenant,)).fetchone()["n"] == 0
