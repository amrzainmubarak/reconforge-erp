"""Original restricted-role proof for a source-owned paired multi-currency cycle."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError, PostingActor, digest_payload
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_intercompany_fx import PostgresIntercompanyFxRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from reconforge.platform.common import ServerPrincipal, server_principal_context
from tests.intercompany_fx_fixture import ACCOUNTS, rate
from tests.intercompany_fx_fixture import preparation as pure_preparation
from tests.test_postgres_inventory_receipt_posting import (
    ReceiptRuntime,
    create_receipt_runtime,
    pytestmark,
    receipt_database,
)

__all__ = ["receipt_database", "pytestmark"]
ENTITIES = frozenset({"seller", "buyer", "group"})
PERIODS = {"seller": "period", "buyer": "period", "adjustment": "period"}


@dataclass
class FxRuntime:
    base: ReceiptRuntime

    @contextmanager
    def actor(self, name: str, *, entities: frozenset[str] = ENTITIES, organization_id: str | None = "org") -> Iterator[tuple[Any, PostgresIntercompanyFxRepository, PostingActor]]:
        boundary = PostgresTenantBoundary(self.base.factory)
        with boundary.transaction(self.base.tenant) as connection:
            identities = PostgresIdentityRepository(connection)
            user = identities.authenticate_user(tenant_id=self.base.tenant, username=name, password=self.base.password)
            assert user is not None
            permissions = identities.user_permissions(tenant_id=self.base.tenant, user_id=user.id)
        with boundary.transaction(self.base.tenant, workspace_id="work", organization_id=organization_id) as connection:
            principal = ServerPrincipal(user=user, permissions=permissions, step_up_active=True,
                authorized_tenant_ids=frozenset({self.base.tenant}), authorized_workspace_ids=frozenset({"work"}),
                authorized_organization_ids=frozenset({"org"}), authorized_legal_entity_ids=entities)
            with server_principal_context(principal):
                yield connection, PostgresIntercompanyFxRepository(connection, self.base.tenant), PostingActor(
                    user.id, user.username, permissions, step_up_active=True)


@pytest.fixture(scope="module")
def intercompany_fx_database(receipt_database: tuple[str, str]) -> tuple[str, str]:
    import psycopg
    from psycopg import sql

    from reconforge.infrastructure.postgres_fx_conversion_sql import UPGRADE_SQL as INVERSE_SQL
    from reconforge.infrastructure.postgres_intercompany_fx_schema import UPGRADE_SQL

    with psycopg.connect(receipt_database[0]) as admin:
        if admin.execute("SELECT to_regprocedure('reconforge.fx_convert_inverse(numeric,numeric,integer,integer)')").fetchone()[0] is None:
            admin.execute(INVERSE_SQL)
        if admin.execute("SELECT to_regclass('reconforge.intercompany_fx_sources')").fetchone()[0] is None:
            admin.execute(UPGRADE_SQL)
        app_user = psycopg.conninfo.conninfo_to_dict(receipt_database[1])["user"]
        admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(sql.Identifier(app_user)))
    return receipt_database


@pytest.fixture
def runtime(intercompany_fx_database: tuple[str, str]) -> FxRuntime:
    base = create_receipt_runtime(intercompany_fx_database)
    return seed_intercompany_fx_masters(base)


def seed_intercompany_fx_masters(base: ReceiptRuntime) -> FxRuntime:
    with PostgresTenantBoundary(base.factory).transaction(base.tenant) as connection:
        for code in ("EUR", "GBP"):
            connection.execute("INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES(%s,%s,%s,2)", (base.tenant, code, code))
        for identifier, code, currency in (("seller", "SELLER", "EUR"), ("buyer", "BUYER", "GBP"), ("group", "GROUP", "USD")):
            connection.execute("INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) VALUES(%s,%s,'org',%s,%s,%s)",
                (base.tenant, identifier, code, code, currency))
        finance = PostgresFinanceCoreRepository(connection, base.tenant)
        for code, kind, _ in ACCOUNTS:
            finance.upsert_account(account_code=code, name=code, account_type=kind,
                normal_balance="Credit" if kind in {"Liability", "Income", "Equity"} else "Debit", chart_code="DEFAULT", workspace="work")
        for currency in ("EUR", "GBP", "USD"):
            finance.upsert_journal(journal_code="IC2_" + currency, name="Captured " + currency,
                organization_code="ORG", currency_code=currency, workspace="work")
        identities = PostgresIdentityRepository(connection)
        for permission in ("finance_core.read", "master_data.manage", "intercompany_fx.read", "intercompany_fx.prepare", "intercompany_fx.review", "intercompany_fx.post"):
            identities.create_permission(tenant_id=base.tenant, permission_name=permission)
            identities.grant_permission(tenant_id=base.tenant, role_name="receipt-operator", permission_name=permission)
        authority = PostgresScopeAuthorityRepository(connection)
        for person in ("maker", "checker", "poster"):
            for kind, identifier in (("workspace", "work"), ("organization", "org"), *(("legal_entity", entity) for entity in sorted(ENTITIES))):
                if connection.execute("SELECT 1 FROM reconforge.principal_scope_grants WHERE tenant_id=%s AND principal_type='user' AND principal_id=%s AND scope_type=%s AND scope_id=%s AND revoked_at IS NULL",
                    (base.tenant, person, kind, identifier)).fetchone() is not None:
                    continue
                authority.grant(tenant_id=base.tenant, grant_id=f"ic2-{person}-{identifier}", principal_type="user", principal_id=person,
                    scope_type=kind, scope_id=identifier, actor_id=person)
    return FxRuntime(base)


def preparation(amount: int = 10001):
    original = pure_preparation(amount=amount)
    return replace(original, seller=replace(original.seller, legal_entity_id="seller", entity_code="SELLER"))


def publish(rt: FxRuntime, plan: dict[str, Any], suffix: str) -> dict[str, Any]:
    with rt.actor("checker") as (_, repository, actor):
        repository.review(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Reviewed exact captured rates and both books", command_id="review-" + suffix, actor=actor)
    with rt.actor("poster") as (_, repository, actor):
        return repository.post(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Third human native publication", command_id="post-" + suffix, actor=actor)


def recognize(rt: FxRuntime) -> dict[str, Any]:
    with rt.actor("maker") as (_, repository, actor):
        plan = repository.prepare(preparation(), command_id="prepare-original", actor=actor)
    return publish(rt, plan, "original")


def cash(rt: FxRuntime, source_id: str, *, transaction_minor: int = 3000, day: str = "2026-10-04", suffix: str = "cash") -> dict[str, Any]:
    with rt.actor("maker") as (_, repository, actor):
        plan = repository.prepare_settlement(source_id, transaction_minor=transaction_minor,
            rates={"seller": rate("1.3", day), "buyer": rate("0.78", day)}, period_ids=PERIODS,
            posting_date=day, reason="Reviewed captured cash rates", command_id="prepare-" + suffix, actor=actor)
    return publish(rt, plan, suffix)


def revalue(rt: FxRuntime, source_id: str) -> dict[str, Any]:
    day = "2026-10-05"
    with rt.actor("maker") as (_, repository, actor):
        plan = repository.prepare_revaluation(source_id, rates={"seller": rate("1.32", day), "buyer": rate("0.82", day)},
            period_ids=PERIODS, posting_date=day, reason="Reviewed period closing observations", command_id="prepare-revalue", actor=actor)
    return publish(rt, plan, "revalue")


def eliminate(rt: FxRuntime, source_id: str) -> dict[str, Any]:
    day = "2026-10-06"
    with rt.actor("maker") as (_, repository, actor):
        plan = repository.prepare_elimination(source_id, closing_rates={"seller": rate("1.32", day), "buyer": rate("0.82", day)},
            income_rates={"seller": {"2026-10-03": rate("1.25", "2026-10-03"), "2026-10-04": rate("1.3", "2026-10-04"), "2026-10-05": rate("1.32", "2026-10-05")},
                          "buyer": {"2026-10-03": rate("0.8", "2026-10-03"), "2026-10-04": rate("0.78", "2026-10-04"), "2026-10-05": rate("0.82", "2026-10-05")}},
            period_ids=PERIODS, posting_date=day, reason="Reviewed actual original and residual translated membership", command_id="prepare-elimination", actor=actor)
    return publish(rt, plan, "elimination")


def test_native_initial_recognition_and_three_actor_evidence(runtime: FxRuntime) -> None:
    original = recognize(runtime)
    assert original["phase"] == 2
    assert original["equation"]["positions"]["seller"]["original_functional_minor"] == 12501
    assert original["equation"]["positions"]["buyer"]["original_functional_minor"] == 8001
    with runtime.actor("poster") as (connection, repository, actor):
        proof = repository.evidence(original["id"], actor=actor)
        assert len(proof["phases"]) == 3
        assert len({phase["actor_id"] for phase in proof["phases"]}) == 3
        assert all(phase["audit_event_id"] and phase["outbox_event_id"] for phase in proof["phases"])
        assert len(proof["native_effects"]) == 2
        assert dict(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == {"rolsuper": False, "rolbypassrls": False}
        with pytest.raises(FinancePostingError, match="Command identity"):
            repository.prepare(preparation(), command_id="prepare-original", actor=actor)


def test_native_partial_revalue_translation_elimination_reports_actual_cta(runtime: FxRuntime) -> None:
    original = recognize(runtime)
    settled = cash(runtime, original["source_id"])
    valued = revalue(runtime, original["source_id"])
    adjustment = eliminate(runtime, original["source_id"])
    assert settled["equation"]["positions"]["seller"]["realized_fx_minor"] == 150
    assert settled["equation"]["positions"]["buyer"]["realized_fx_minor"] == 60
    assert valued["equation"]["positions"]["seller"]["unrealized_fx_minor"] == 490
    assert valued["equation"]["positions"]["buyer"]["unrealized_fx_minor"] == -140
    assert adjustment["equation"]["translated_trade_minor"] == 10001
    assert adjustment["equation"]["translated_residual_minor"] == 7001
    with runtime.actor("poster") as (connection, repository, actor):
        report = repository.report(original["source_id"], actor=actor)
        assert report["report_digest"] == digest_payload({key: value for key, value in report.items() if key != "report_digest"})
        assert report["income_statement"] == {"income_minor": 563, "expense_minor": 171, "result_minor": 392}
        assert report["cash_net_movement_minor"] == 101
        assert report["cta_minor"] == -291
        assert len(report["source_effect_ids"]) == 6 and len(report["native_adjustment_effect_ids"]) == 1
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.base.tenant,)).fetchone()["n"] == 7
        export_cycle(connection, repository, actor, [original, settled, valued, adjustment], report)


def test_direct_native_partial_review_and_manual_publication_refused(runtime: FxRuntime) -> None:
    import psycopg

    with runtime.actor("maker") as (_, repository, actor):
        prepared = repository.prepare(preparation(), command_id="prepare-original", actor=actor)
        with pytest.raises(FinancePostingError, match="independent"):
            repository.review(prepared["id"], expected_plan_digest=prepared["plan_digest"], reason="Self", command_id="self", actor=actor)
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor("checker") as (connection, repository, actor):
        repository.owner.finance.validate_entry(prepared["entries"][0]["entry_id"], reason="Detached half", actor_label=actor.username)
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    posted = publish(runtime, prepared, "original")
    with runtime.actor("poster") as (_, repository, actor):
        with pytest.raises(FinancePostingError, match="source|owner|complete"):
            repository.owner.posting.post(prepared["entries"][0]["entry_id"], command_id="detached", expected_validation_digest=prepared["entries"][0]["validation_digest"], reason="Detached", actor=actor)
        with pytest.raises(FinancePostingError, match="source|owner|inverse"):
            repository.owner.posting.prepare_reversal(next(iter(posted["posting_effect_ids"].values())), command_id="detached-inverse", entry_number="DETACHED", period_id="period", posting_date="2026-10-04", reason="Detached", actor=actor)


def backing_digest(connection: Any, tenant: str) -> str:
    from psycopg import sql

    tables = ("intercompany_fx_sources", "intercompany_fx_plans", "intercompany_fx_reviews", "intercompany_fx_links", "intercompany_fx_post_evidence", "intercompany_fx_commands",
        "finance_entries", "finance_entry_lines", "finance_posting_effects", "finance_posting_commands", "domain_audit_events", "domain_audit_ledger_state", "outbox_events")
    return digest_payload({table: [row["payload"] for row in connection.execute(sql.SQL("SELECT to_jsonb(t) payload FROM reconforge.{} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text").format(sql.Identifier(table)), (tenant,))] for table in tables})


def export_cycle(connection: Any, repository: PostgresIntercompanyFxRepository, actor: PostingActor, stages: list[dict[str, Any]], report: dict[str, Any] | None = None) -> None:
    import json
    import os
    from pathlib import Path
    from uuid import uuid4

    if directory := os.environ.get("RECONFORGE_ICFX_PROOF_DIR"):
        proof = {"schema_version": "intercompany-fx-original-cycle-proof-v2", "performance_measurement": False,
            "native_role": dict(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()),
            "stages": [repository.evidence(stage["id"], actor=actor) for stage in stages], "report": report}
        Path(directory, "cycle-" + uuid4().hex + ".json").write_text(json.dumps(proof, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def test_full_settlement_after_governed_revaluation_inverse(runtime: FxRuntime) -> None:
    original = recognize(runtime)
    first_cash = cash(runtime, original["source_id"])
    valued = revalue(runtime, original["source_id"])
    with runtime.actor("maker") as (_, repository, actor):
        inverse = repository.prepare_revaluation_reversal(original["source_id"], original_revaluation_id=valued["id"], period_ids=PERIODS,
            posting_date="2026-10-06", reason="Exact retained closing observation inverse", command_id="prepare-inverse", actor=actor)
    reversed_plan = publish(runtime, inverse, "inverse")
    assert reversed_plan["equation"]["original_posting_effect_ids"] == valued["posting_effect_ids"]
    for entry in reversed_plan["entries"]:
        previous = next(item for item in valued["entries"] if item["book"] == entry["book"])
        assert entry["reverses_effect_id"] == valued["posting_effect_ids"][entry["book"]]
        assert [(row["debit_minor"], row["credit_minor"]) for row in entry["snapshot"]["lines"]] == [(row["credit_minor"], row["debit_minor"]) for row in previous["snapshot"]["lines"]]
    final = cash(runtime, original["source_id"], transaction_minor=7001, day="2026-10-07", suffix="final-cash")
    assert final["equation"]["transaction_after_minor"] == 10001
    with runtime.actor("poster") as (connection, repository, actor):
        assert repository.get_source(original["source_id"], actor=actor)["state"]["active_revaluation_id"] is None
        for book in ("seller", "buyer"):
            entity = preparation().payload()[book]
            balance = connection.execute("""SELECT sum((n->>'debit_minor')::bigint-(n->>'credit_minor')::bigint) balance
                FROM reconforge.finance_posting_effects f CROSS JOIN LATERAL jsonb_array_elements(f.snapshot_json->'lines')n
                JOIN reconforge.finance_accounts a ON a.tenant_id=f.tenant_id AND a.id=n->>'account_id'
                WHERE f.tenant_id=%s AND f.legal_entity_id=%s AND a.account_code=%s""", (runtime.base.tenant, entity["legal_entity_id"], entity["accounts"]["party"])).fetchone()["balance"]
            assert balance == 0
        export_cycle(connection, repository, actor, [original, first_cash, valued, reversed_plan, final])
        with pytest.raises(FinancePostingError, match="residual"):
            repository.prepare_revaluation(original["source_id"], rates={"seller": rate("1.32", "2026-10-08"), "buyer": rate("0.82", "2026-10-08")},
                period_ids=PERIODS, posting_date="2026-10-08", reason="No residual", command_id="no-residual", actor=actor)


def test_late_second_effect_failure_rolls_back_pair_commands_audit_outbox(runtime: FxRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    with runtime.actor("maker") as (_, repository, actor):
        plan = repository.prepare(preparation(), command_id="prepare-original", actor=actor)
    with runtime.actor("checker") as (_, repository, actor):
        repository.review(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Reviewed whole pair", command_id="review-original", actor=actor)
    with runtime.actor("poster") as (connection, repository, actor):
        before = backing_digest(connection, runtime.base.tenant)
        original_post = repository.owner.posting.post
        calls = 0

        def fail_second(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            result = original_post(*args, **kwargs)
            if calls == 2:
                raise RuntimeError("Synthetic late second effect failure")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(repository.owner.posting, "post", fail_second)
            with pytest.raises(RuntimeError, match="late second"):
                repository.post(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Publish pair", command_id="post-original", actor=actor)
        assert backing_digest(connection, runtime.base.tenant) == before
        result = repository.post(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Publish pair", command_id="post-original", actor=actor)
        assert repository.post(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Publish pair", command_id="post-original", actor=actor) == result


def test_competing_pending_cash_and_exact_lost_ack_replay(runtime: FxRuntime) -> None:
    original = recognize(runtime)

    def prepare_cash(command: str) -> Any:
        try:
            with runtime.actor("maker") as (_, repository, actor):
                return repository.prepare_settlement(original["source_id"], transaction_minor=7000,
                    rates={"seller": rate("1.3", "2026-10-04"), "buyer": rate("0.78", "2026-10-04")}, period_ids=PERIODS,
                    posting_date="2026-10-04", reason="Competing original cash", command_id=command, actor=actor)
        except FinancePostingError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(prepare_cash, ("cash-one", "cash-two")))
    assert sum(isinstance(result, dict) for result in results) == 1
    winner = next(result for result in results if isinstance(result, dict))
    publish(runtime, winner, "cash")
    command = "cash-one" if isinstance(results[0], dict) else "cash-two"
    with ThreadPoolExecutor(max_workers=2) as workers:
        replays = list(workers.map(prepare_cash, (command, command)))
    assert replays == [winner, winner]


@pytest.mark.parametrize("mutation", ["source_rate", "source_map", "plan_translation", "rename", "line_amount", "delete_line"])
def test_direct_sql_source_rates_maps_equations_and_old_header_relevance(runtime: FxRuntime, mutation: str) -> None:
    import psycopg

    with runtime.actor("maker") as (_, repository, actor):
        plan = repository.prepare(preparation(), command_id="prepare-original", actor=actor)
    if mutation == "line_amount":
        verify_native_line_update_refusal(runtime, plan)
        return
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor("maker") as (connection, _, _):
        if mutation in {"source_rate", "source_map"}:
            path = "{request,seller_original_rate,rate}" if mutation == "source_rate" else "{native_accounts,seller,party,account_code}"
            connection.execute("UPDATE reconforge.intercompany_fx_sources SET payload=jsonb_set(payload,%s::text[],'\"9\"') WHERE tenant_id=%s AND id=%s", (path, runtime.base.tenant, plan["source_id"]))
        elif mutation == "plan_translation":
            connection.execute("UPDATE reconforge.intercompany_fx_plans SET payload=jsonb_set(payload,'{equation,transaction_minor}','10002') WHERE tenant_id=%s AND id=%s", (runtime.base.tenant, plan["id"]))
        elif mutation == "rename":
            connection.execute("UPDATE reconforge.finance_entries SET entry_number='LAUNDERED' WHERE tenant_id=%s AND id=%s", (runtime.base.tenant, plan["entries"][0]["entry_id"]))
        else:
            connection.execute("DELETE FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND entry_id=%s", (runtime.base.tenant, plan["entries"][0]["entry_id"]))
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


def verify_native_line_update_refusal(runtime: FxRuntime, plan: dict[str, Any]) -> None:
    import json
    from pathlib import Path
    from uuid import uuid4

    import psycopg

    entry = plan["entries"][0]
    with runtime.actor("maker") as (connection, _, _):
        def original_rows() -> list[dict[str, Any]]:
            return [dict(row) for row in connection.execute("SELECT id,line_number,debit_minor,credit_minor,currency_code FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND entry_id=%s ORDER BY line_number",
                (runtime.base.tenant, entry["entry_id"]))]

        before = original_rows()
        assert len(before) == len(entry["snapshot"]["lines"]) and sum(row["debit_minor"] > 0 for row in before) == 1
        group_touched = None
        group_guard_refused = False
        try:
            with connection.transaction():
                group_touched = connection.execute("UPDATE reconforge.finance_entry_lines SET debit_minor=debit_minor+1 WHERE tenant_id=%s AND entry_id=%s AND debit_minor>0 RETURNING id",
                    (runtime.base.tenant, entry["entry_id"])).rowcount
                assert group_touched in {0, 1}
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        except psycopg.errors.CheckViolation:
            group_guard_refused = True
        assert group_guard_refused or group_touched == 0
        assert original_rows() == before
        # A zero-row group-context UPDATE is RLS refusal, not execution of the
        # financial closure. Exercise the visible native book separately.
        native_touched = None
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            entity = entry["snapshot"]["entry"]["legal_entity_id"]
            connection.execute("SELECT set_config('app.entity_id',%s,true),set_config('app.legal_entity_id',%s,true)", (entity, entity))
            assert original_rows() == before
            native_touched = connection.execute("UPDATE reconforge.finance_entry_lines SET debit_minor=debit_minor+1 WHERE tenant_id=%s AND entry_id=%s AND debit_minor>0 RETURNING id",
                (runtime.base.tenant, entry["entry_id"])).rowcount
            assert native_touched == 1
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert original_rows() == before
        directory = Path(__file__).resolve().parents[1] / "output/m1-ic2-line-mutation"
        directory.mkdir(parents=True, exist_ok=True)
        proof = {"schema_version": "ic2-native-line-refusal-v1", "group_touched_rows": group_touched,
            "group_guard_refused": group_guard_refused, "native_book_touched_rows": native_touched,
            "native_guard_refused_before_returning": native_touched is None, "original_population": len(before),
            "original_rows_sha256": digest_payload(before), "original_rows_unchanged": True}
        with (directory / ("original-line-refusal-" + uuid4().hex + ".json")).open("x", encoding="utf8") as handle:
            json.dump(proof, handle, sort_keys=True, separators=(",", ":"))


def test_current_grant_revocation_after_actual_source_wait_refuses_review(runtime: FxRuntime) -> None:
    from queue import Queue
    from time import monotonic, sleep

    with runtime.actor("maker") as (_, repository, actor):
        plan = repository.prepare(preparation(), command_id="prepare-original", actor=actor)
    pids: Queue[int] = Queue()

    def review() -> Any:
        try:
            with runtime.actor("checker") as (connection, repository, actor):
                pids.put(connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"])
                return repository.review(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Wait then reauthorize", command_id="blocked-review", actor=actor)
        except FinancePostingError as exc:
            return exc

    blocker = runtime.base.factory.connect()
    blocker.execute("SELECT set_config('app.tenant_id',%s,true),set_config('app.workspace_id','work',true),set_config('app.organization_id','org',true)", (runtime.base.tenant,))
    blocker_pid = blocker.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]
    blocker.execute("SELECT id FROM reconforge.intercompany_fx_sources WHERE tenant_id=%s AND id=%s FOR UPDATE", (runtime.base.tenant, plan["source_id"]))
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(review)
            pid = pids.get(timeout=10)
            with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
                deadline = monotonic() + 10
                while blocker_pid not in connection.execute("SELECT pg_blocking_pids(%s) pids", (pid,)).fetchone()["pids"]:
                    assert monotonic() < deadline, "Actual source-row wait was not established"
                    sleep(.02)
                PostgresScopeAuthorityRepository(connection).revoke(tenant_id=runtime.base.tenant, grant_id="ic2-checker-group", actor_id="maker", reason="Withdraw original group authority during source wait")
            blocker.rollback()
            result = future.result(timeout=15)
            assert isinstance(result, FinancePostingError) and "denied" in result.code
    finally:
        blocker.rollback()
        blocker.close()
    with runtime.actor("poster") as (connection, repository, actor):
        assert repository.get_plan(plan["id"], actor=actor)["phase"] == 0
        assert connection.execute("SELECT count(*) n FROM reconforge.intercompany_fx_commands WHERE tenant_id=%s AND command_id='blocked-review'", (runtime.base.tenant,)).fetchone()["n"] == 0


def test_scoped_fiscal_close_and_reasoned_reopen_preserve_original_commands(runtime: FxRuntime) -> None:
    from reconforge.infrastructure.postgres_master_data import (
        PostgresMasterDataRepository,
        PostgresMasterDataValidationError,
    )

    original = recognize(runtime)
    with runtime.actor("poster", organization_id=None) as (connection, _, actor):
        masters = PostgresMasterDataRepository(connection)
        masters.set_period_status(tenant_id=runtime.base.tenant, period_id="period", status="Soft Closed", reason="Reviewed soft close", actor_id=actor.user_id)
        masters.set_period_status(tenant_id=runtime.base.tenant, period_id="period", status="Closed", reason="Reviewed period closure", actor_id=actor.user_id)
    with runtime.actor("maker") as (_, repository, actor):
        assert repository.prepare(preparation(), command_id="prepare-original", actor=actor)["phase"] == 0
        with pytest.raises(FinancePostingError, match="open"):
            repository.prepare_settlement(original["source_id"], transaction_minor=3000, rates={"seller": rate("1.3", "2026-10-04"), "buyer": rate("0.78", "2026-10-04")},
                period_ids=PERIODS, posting_date="2026-10-04", reason="Locked period", command_id="locked-cash", actor=actor)
    with runtime.actor("checker", organization_id=None) as (connection, _, actor):
        masters = PostgresMasterDataRepository(connection)
        with pytest.raises(PostgresMasterDataValidationError, match="reason"):
            masters.set_period_status(tenant_id=runtime.base.tenant, period_id="period", status="Open", actor_id=actor.user_id)
        masters.set_period_status(tenant_id=runtime.base.tenant, period_id="period", status="Open", reason="Reviewed source correction", actor_id=actor.user_id)
    assert cash(runtime, original["source_id"])["phase"] == 2


def test_actual_populated_restore_keeps_original_effects_current_authority_and_object_guards(runtime: FxRuntime) -> None:
    from tests.intercompany_fx_native_restore import verify_restore

    original = recognize(runtime)
    cash(runtime, original["source_id"])
    revalue(runtime, original["source_id"])
    eliminate(runtime, original["source_id"])
    result = verify_restore(runtime, original["source_id"])
    assert result["status"] == "passed" and result["owned_restore_database_removed"]
    assert result["tamper_refusals"] == 3


def test_populated_downgrade_refuses_to_drop_retained_source_history(runtime: FxRuntime) -> None:
    import psycopg

    from reconforge.infrastructure.postgres_intercompany_fx_schema import DOWNGRADE_SQL

    original = recognize(runtime)
    with psycopg.connect(runtime.base.admin_dsn) as admin, pytest.raises(psycopg.errors.RaiseException, match="refuses"), admin.transaction():
        admin.execute(DOWNGRADE_SQL)
    with runtime.actor("poster") as (_, repository, actor):
        assert repository.get_plan(original["id"], actor=actor) == original


@pytest.mark.parametrize("identifier,number", [("ic2-orphan", "ORDINARY"), ("IC2R-orphan", "ORDINARY"), ("ordinary-orphan", "ic2s-orphan"), ("ordinary-orphan", "ic2e-orphan")])
def test_reserved_upper_and_lower_ids_and_numbers_require_exact_source_owner(runtime: FxRuntime, identifier: str, number: str) -> None:
    import psycopg

    with runtime.actor("maker") as (_, repository, actor):
        plan = repository.prepare(preparation(), command_id="prepare-original", actor=actor)
    with pytest.raises(psycopg.errors.CheckViolation) as denied, runtime.actor("maker") as (connection, _, _):
        connection.execute("""INSERT INTO reconforge.finance_entries SELECT (jsonb_populate_record(NULL::reconforge.finance_entries,
            to_jsonb(e)||jsonb_build_object('id',%s::text,'entry_number',%s::text))).* FROM reconforge.finance_entries e WHERE e.tenant_id=%s AND e.id=%s""",
            (identifier, number, runtime.base.tenant, plan["entries"][0]["entry_id"]))
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert denied.value.diag.constraint_name == "intercompany_fx_owner"


def test_direct_inverse_command_checks_current_reverse_permission(runtime: FxRuntime) -> None:
    import psycopg

    original = recognize(runtime)
    cash(runtime, original["source_id"])
    valued = revalue(runtime, original["source_id"])
    with runtime.actor("maker") as (_, repository, actor):
        inverse = repository.prepare_revaluation_reversal(original["source_id"], original_revaluation_id=valued["id"], period_ids=PERIODS,
            posting_date="2026-10-06", reason="Retained exact inverse", command_id="prepare-inverse", actor=actor)
    with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
        connection.execute("UPDATE reconforge.identity_role_permissions SET active=false,revoked_at=now(),revoked_by='poster',revocation_reason_code='access_change' WHERE tenant_id=%s AND permission_name='finance_core.reverse'", (runtime.base.tenant,))
    with pytest.raises(psycopg.errors.CheckViolation, match="reverse permission"), runtime.actor("maker") as (connection, _, actor):
        connection.execute("""INSERT INTO reconforge.intercompany_fx_commands SELECT
            tenant_id,workspace_id,organization_id,seller_entity_id,buyer_entity_id,adjustment_entity_id,plan_id,'review',%s,%s,
            request_digest,request_json,response_json FROM reconforge.intercompany_fx_commands WHERE tenant_id=%s AND plan_id=%s AND operation='prepare'""",
            ("forged-inverse-review", actor.user_id, runtime.base.tenant, inverse["id"]))


def test_canonical_inverse_native_half_up_ties_large_coefficient_and_overflow(runtime: FxRuntime) -> None:
    from fractions import Fraction

    import psycopg

    def rounded(value: Fraction) -> int:
        sign = -1 if value < 0 else 1
        whole, remainder = divmod(abs(value).numerator, abs(value).denominator)
        return sign * (whole + (2 * remainder >= abs(value).denominator))

    vectors = [(minor, ratio, base, quote) for minor in (0, 1, -1, 2, -2, 10001, 9_000_000_000_000_000_000)
        for ratio, base, quote in (("2", 2, 2), ("1.999999999999", 0, 0), ("2.000000000001", 0, 0), ("999999999999.999999999999", 8, 0))]
    vectors.append((9_000_000_000_000_000_000, "0.000000000001", 0, 8))
    with runtime.actor("poster") as (connection, _, _):
        for amount, ratio, base, quote in vectors:
            expected = rounded(Fraction(amount) / Fraction(ratio) * Fraction(10 ** quote, 10 ** base))
            if abs(expected) > 9_000_000_000_000_000_000:
                with pytest.raises(psycopg.errors.CheckViolation, match="native minor-unit bound"), connection.transaction():
                    connection.execute("SELECT reconforge.fx_convert_inverse(%s::numeric,%s::numeric,%s,%s)", (str(amount), ratio, base, quote))
            else:
                actual = connection.execute("SELECT reconforge.fx_convert_inverse(%s::numeric,%s::numeric,%s,%s) amount", (str(amount), ratio, base, quote)).fetchone()["amount"]
                assert actual == expected


def test_native_two_installments_preserve_actual_half_up_final_carry(runtime: FxRuntime) -> None:
    with runtime.actor("maker") as (_, repository, actor):
        initial = repository.prepare(preparation(amount=2), command_id="prepare-original", actor=actor)
    original = publish(runtime, initial, "original")
    assert original["equation"]["positions"]["seller"]["original_functional_minor"] == 3
    first = cash(runtime, original["source_id"], transaction_minor=1)
    second = cash(runtime, original["source_id"], transaction_minor=1, day="2026-10-05", suffix="final")
    assert first["equation"]["positions"]["seller"]["historical_release_minor"] == 1
    assert second["equation"]["positions"]["seller"]["historical_release_minor"] == 2
    with runtime.actor("poster") as (connection, repository, actor):
        export_cycle(connection, repository, actor, [original, first, second])


def test_emitted_source_history_rechecks_current_revalued_amount_ceiling(runtime: FxRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    from decimal import Decimal

    import reconforge.infrastructure.postgres_operational_finance as authority
    from reconforge.auth.policy import evaluate_principal_access

    cfg = preparation()
    cfg = replace(cfg, seller_original_rate=rate("1.425", "2026-10-03"))
    with runtime.actor("maker") as (_, repository, actor):
        prepared = repository.prepare(cfg, command_id="prepare-original", actor=actor)
    original = publish(runtime, prepared, "original")
    assert original["equation"]["positions"]["seller"]["original_functional_minor"] == 14251
    with runtime.actor("maker") as (_, repository, actor):
        value = repository.prepare_revaluation(original["source_id"], rates={"seller": rate("2.052", "2026-10-04"), "buyer": rate("0.82", "2026-10-04")}, period_ids=PERIODS,
            posting_date="2026-10-04", reason="Explicit current exposure", command_id="prepare-revalue", actor=actor)
    publish(runtime, value, "revalue")
    assert value["equation"]["positions"]["seller"]["valued_outstanding_minor"] == 20522

    def ceiling(principal: Any, **context: Any) -> Any:
        return evaluate_principal_access(principal, maximum_amount=Decimal("150"), **context)

    with monkeypatch.context() as patch, runtime.actor("poster") as (_, repository, actor):
        patch.setattr(authority, "evaluate_principal_access", ceiling)
        with pytest.raises(FinancePostingError, match="denied"):
            repository.get_source(original["source_id"], actor=actor)
        with pytest.raises(FinancePostingError, match="denied"):
            repository.get_plan(value["id"], actor=actor)


def test_sorted_period_locks_precede_currency_binding_during_actual_wait(runtime: FxRuntime) -> None:
    from queue import Queue
    from time import monotonic, sleep

    from reconforge.infrastructure.finance_policy_store import FinancePolicyStore

    pids: Queue[int] = Queue()

    def prepare() -> dict[str, Any]:
        with runtime.actor("maker") as (connection, repository, actor):
            pids.put(connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"])
            return repository.prepare(preparation(), command_id="prepare-original", actor=actor)

    blocker = runtime.base.factory.connect()
    blocker.execute("SELECT set_config('app.tenant_id',%s,true),set_config('app.workspace_id','work',true),set_config('app.organization_id','org',true)", (runtime.base.tenant,))
    blocker.execute("SELECT id FROM reconforge.fiscal_periods WHERE tenant_id=%s AND id='period' FOR UPDATE", (runtime.base.tenant,))
    blocker_pid = blocker.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(prepare)
            pid = pids.get(timeout=10)
            with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as control:
                deadline = monotonic() + 10
                while blocker_pid not in control.execute("SELECT pg_blocking_pids(%s) pids", (pid,)).fetchone()["pids"]:
                    assert monotonic() < deadline, "Actual fiscal-period lock wait was not established"
                    sleep(.02)
                control.execute("SET LOCAL statement_timeout='1s'")
                FinancePolicyStore(control, tenant_id=runtime.base.tenant).lock_binding("work")
            blocker.rollback()
            assert future.result(timeout=20)["phase"] == 0
    finally:
        blocker.rollback()
        blocker.close()


def test_ordinary_manual_native_inverse_needs_no_intercompany_table_select(runtime: FxRuntime) -> None:
    import psycopg
    from psycopg import sql

    with runtime.actor("maker") as (_, repository, actor):
        entry = repository.owner.finance.create_entry(entry_number="ORDINARY-ORIGINAL", organization_code="ORG", entity_code="SELLER",
            journal_code="IC2_EUR", period_id="period", posting_date="2026-10-03", description="Ordinary native source", workspace="work",
            actor_label=actor.username, lines=[{"account_code": "IC2_CASH", "debit": "1", "credit": "0", "description": "Ordinary"},
                {"account_code": "IC2_EXP", "debit": "0", "credit": "1", "description": "Ordinary"}])
    with runtime.actor("checker") as (_, repository, actor):
        repository.owner.finance.validate_entry(entry["id"], reason="Ordinary independent review", actor_label=actor.username)
    with runtime.actor("poster") as (_, repository, actor):
        preview = repository.owner.posting.preview(entry["id"], actor=actor)
        original = repository.owner.posting.post(entry["id"], command_id="ordinary-post", expected_validation_digest=preview["validation_digest"], reason="Ordinary publication", actor=actor)
    role = psycopg.conninfo.conninfo_to_dict(runtime.base.factory.settings.dsn)["user"]
    tables = ("intercompany_fx_sources", "intercompany_fx_plans", "intercompany_fx_reviews", "intercompany_fx_links", "intercompany_fx_post_evidence", "intercompany_fx_commands")
    with psycopg.connect(runtime.base.admin_dsn) as admin:
        for table in tables:
            admin.execute(sql.SQL("REVOKE SELECT ON reconforge.{} FROM {}").format(sql.Identifier(table), sql.Identifier(role)))
    try:
        with runtime.actor("maker") as (_, repository, actor):
            inverse = repository.owner.posting.prepare_reversal(original["id"], command_id="ordinary-inverse", entry_number="ORDINARY-INVERSE",
                period_id="period", posting_date="2026-10-04", reason="Ordinary native inverse", actor=actor)
        with runtime.actor("checker") as (_, repository, actor):
            repository.owner.finance.validate_entry(inverse["entry_id"], reason="Ordinary inverse review", actor_label=actor.username)
        with runtime.actor("poster") as (_, repository, actor):
            preview = repository.owner.posting.preview(inverse["entry_id"], actor=actor)
            effect = repository.owner.posting.post(inverse["entry_id"], command_id="ordinary-inverse-post", expected_validation_digest=preview["validation_digest"], reason="Ordinary inverse publication", actor=actor)
            assert effect["reverses_effect_id"] == original["id"]
    finally:
        with psycopg.connect(runtime.base.admin_dsn) as admin:
            for table in tables:
                admin.execute(sql.SQL("GRANT SELECT ON reconforge.{} TO {}").format(sql.Identifier(table), sql.Identifier(role)))


@pytest.mark.parametrize("debit,credit", [("4500000000000000001", "0"), ("0", "4500000000000000001"), ("0.5", "0"), ("0", "0"), ("1", "1")])
def test_sql_native_source_line_cap_matches_declared_domain_bound(runtime: FxRuntime, debit: str, credit: str) -> None:
    import psycopg

    with runtime.actor("poster") as (connection, _, _):
        with pytest.raises(psycopg.errors.CheckViolation, match="bounded exact native side"), connection.transaction():
            connection.execute("SELECT reconforge.icfx_line('IC2_CASH',%s::numeric,%s::numeric)", (debit, credit))
        line = connection.execute("SELECT reconforge.icfx_line('IC2_CASH',4500000000000000000,0) line").fetchone()["line"]
        assert line == {"account_code": "IC2_CASH", "debit_minor": 4500000000000000000, "credit_minor": 0}
