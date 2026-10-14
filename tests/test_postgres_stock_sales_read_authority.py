"""Genuine KWD3 price and current-authority contracts on ordinary PostgreSQL.

The resumed cases are independently reconstructed from committed fixtures. They
do not claim custody of the missing, previously uncommitted nine-case report.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from queue import Queue
from threading import Event
from typing import Any

import psycopg
import pytest

from reconforge.auth.policy import evaluate_principal_access
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.stock_commerce import CommercialLine, CommercialOrder
from reconforge.domain.stock_sales import StockOrder
from reconforge.infrastructure import postgres_operational_finance as financial_policy
from reconforge.infrastructure import postgres_sales_revenue as sales_policy
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from reconforge.infrastructure.postgres_stock_commerce import PostgresStockCommerceRepository
from reconforge.infrastructure.postgres_stock_sales import READ
from reconforge.platform.common import ServerPrincipal, current_server_principal, server_principal_context
from tests.test_postgres_customer_return_read_authority import (
    SCOPE,
    KwdRuntime,
    _original_tables,
    _retain,
    _retire,
    _RollbackProbe,
    _setup,
    _stock,
    _wait_on,
)
from tests.test_postgres_inventory_receipt_posting import receipt_database

_ = receipt_database


def _preserved(runtime: KwdRuntime, before: dict[str, str], label: str) -> None:
    after = _original_tables(runtime)
    # Retain all original bytes BEFORE deriving the finite coordination boundary.
    _retain("stock-original-preservation-" + label + ".json", {"before": before, "after": after})
    assert len(before) == len(after) == 67 and set(before) == set(after)
    gates = "inventory_quantity_claim_gates"
    assert all(before[name] == after[name] for name in before if name != gates)

    def identities(raw: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for row in json.loads(raw):
            assert type(row["version"]) is int and row["version"] > 0
            identity = json.dumps({key: value for key, value in row.items() if key != "version"}, sort_keys=True)
            assert identity not in result
            result[identity] = row["version"]
        return result

    old, current = identities(before[gates]), identities(after[gates])
    assert set(old) == set(current) and all(current[key] >= value for key, value in old.items())


def _request(number: str = "KWD_FRACTIONAL") -> StockOrder:
    return StockOrder(number, "KWD_CUSTOMER", "SYNTHETIC", "KWD_ITEM", "KWD_MAIN", "STOCK",
        "0.001", 3000000, "KWD", "2026-10-09", "Original 0.001KG merchandise")


def _originals(runtime: KwdRuntime, sale: dict[str, Any]) -> dict[str, dict[str, Any]]:
    with runtime.actor("maker") as (connection, _, _):
        rows = connection.execute("""SELECT operation,command_id,request,result FROM reconforge.stock_sales_commands
            WHERE tenant_id=%s AND order_id=%s ORDER BY version""", (runtime.tenant, sale["id"])).fetchall()
        originals = {row["operation"]: dict(row) for row in rows}
        assert len(originals) == 13
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s",
            (runtime.tenant,)).fetchone()["n"] == 4
    assert sale["status"] == "Paid" and sale["total_minor"] == "3000"
    assert sale["unit_price_minor"] == sale["net_unit_price_minor"] == "3000000"
    return originals


def _read(connection: Any, runtime: KwdRuntime, sale: dict[str, Any], originals: dict[str, dict[str, Any]],
          actor: PostingActor, operation: str) -> dict[str, Any]:
    owner = _stock(connection, runtime)
    if operation == "get":
        result = owner.get(sale["id"], actor=actor)
        assert result == sale
    elif operation == "list":
        result = owner.list(actor=actor)["orders"][0]
        assert result == sale
    elif operation == "historical-create-replay":
        result = owner.create(_request(), command_id=originals["create"]["command_id"], actor=actor)
        assert result == originals["create"]["result"]
    else:
        assert operation == "historical-submit-replay"
        original = originals["submit"]
        parameters = original["request"]["payload"]
        result = owner.act(sale["id"], "submit", expected_version=parameters["expected_version"],
            command_id=original["command_id"], reason=parameters["reason"], parameters={}, actor=actor)
        assert result == original["result"]
    assert result["unit_price_minor"] == "3000000"
    return result


def _denied_reads(connection: Any, runtime: KwdRuntime, sale: dict[str, Any],
                  originals: dict[str, dict[str, Any]], actor: PostingActor) -> None:
    for operation in ("get", "list", "historical-create-replay", "historical-submit-replay"):
        with pytest.raises(FinancePostingError) as denied:
            _read(connection, runtime, sale, originals, actor, operation)
        assert "denied" in denied.value.code


def test_actual_fractional_stock_quote_requires_all_four_finite_read_amount_contexts(
        receipt_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    from reconforge.infrastructure import postgres_stock_sales as original_owner

    assert Path(original_owner.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1])
    runtime, sale = _setup(receipt_database)
    originals = _originals(runtime, sale)
    baseline = _original_tables(runtime)
    selected, maximum = "finance_core.read", Decimal("20")
    observations: list[dict[str, Any]] = []
    violations: list[str] = []

    def financial(principal: ServerPrincipal, **context: Any) -> Any:
        if context["required_permission"] == selected:
            observations.append({"alias": "captured-financial-context", "permission": selected,
                "amount": str(context["amount"]) if context["amount"] is not None else None, "maximum": str(maximum)})
            return evaluate_principal_access(principal, maximum_amount=maximum, **context)
        return evaluate_principal_access(principal, **context)

    def sales(principal: ServerPrincipal, **context: Any) -> Any:
        # The existing generic scope admission has no financial subject. The
        # configured monetary bound applies to genuine money-bearing calls,
        # including birth/create before a captured policy exists.
        if context["required_permission"] == selected and context["amount"] is not None:
            observations.append({"alias": "birth-current-currency-context", "permission": selected,
                "amount": str(context["amount"]), "maximum": str(maximum)})
            return evaluate_principal_access(principal, maximum_amount=maximum, **context)
        return evaluate_principal_access(principal, **context)

    monkeypatch.setattr(financial_policy, "evaluate_principal_access", financial)
    monkeypatch.setattr(sales_policy, "evaluate_principal_access", sales)
    for index, permission in enumerate(sorted(READ)):
        selected, maximum = permission, Decimal("20")
        for operation in ("get", "list", "historical-create-replay", "historical-submit-replay"):
            with runtime.actor("maker") as (connection, _, actor):
                try:
                    _read(connection, runtime, sale, originals, actor, operation)
                    violations.append(permission + ":" + operation)
                except FinancePostingError as refused:
                    assert "denied" in refused.code
        with runtime.actor("maker") as (connection, _, actor):
            try:
                with connection.transaction():
                    result = _stock(connection, runtime).create(_request("KWD-NEW-READ-" + str(index)),
                        command_id="stock-new-price-" + str(index), actor=actor)
                    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
                    assert result["unit_price_minor"] == "3000000"
                    _retain("stock-unexpected-new-ack-" + permission + ".json", result)
                    violations.append(permission + ":new-create-ack")
                    raise _RollbackProbe()
            except _RollbackProbe:
                pass
            except FinancePostingError as refused:
                assert "denied" in refused.code
        maximum = Decimal("4000")
        for operation in ("get", "list", "historical-create-replay", "historical-submit-replay"):
            with runtime.actor("maker") as (connection, _, actor):
                _read(connection, runtime, sale, originals, actor, operation)
        with runtime.actor("maker") as (connection, _, actor):
            try:
                with connection.transaction():
                    high = _stock(connection, runtime).create(_request("KWD-HIGH-READ-" + str(index)),
                        command_id="stock-high-price-" + str(index), actor=actor)
                    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
                    assert high["unit_price_minor"] == "3000000"
                    _retain("stock-positive-new-ack-" + permission + ".json", high)
                    raise _RollbackProbe()
            except _RollbackProbe:
                pass
        maximum = Decimal("20")
        _preserved(runtime, baseline, "read-" + permission)
    _retain("stock-original-price-read-observations.json", {"quoted_unit_minor": 3000000,
        "net_unit_minor": 3000000, "invoice_minor": 3000, "cogs_minor": 1, "precision": 3,
        "observations": observations, "unexpected_admissions": violations, "original_source": sale,
        "original_commands": originals, "original_66_financial_tables_unchanged": True,
        "coordination_gate_classification": "Exact tenant/pool/cardinality/all other fields; only known version may monotonically advance",
        "scope_of_configuration": "Actual monetary SDK contexts; generic no-amount scope admissions retain their existing central policy",
        "persisted_sql_amount_ceiling_proven": False})
    assert not violations, "Original unit price exceeds the configured financial READ cap: " + ", ".join(violations)


def test_actual_stock_cached_and_fresh_reads_recheck_original_parent_grants(receipt_database: tuple[str, str]) -> None:
    runtime, sale = _setup(receipt_database)
    originals = _originals(runtime, sale)
    baseline = _original_tables(runtime)
    with runtime.actor("maker") as (_, _, actor):
        cached = current_server_principal()
        assert cached is not None
    violations: list[str] = []
    observations = []
    for kind in ("workspace", "organization", "legal_entity"):
        with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, **SCOPE) as connection:
            try:
                with connection.transaction():
                    assert _retire(connection, runtime.tenant, kind) == 1
                    active = PostgresScopeAuthorityRepository(connection).active_for_principal(
                        tenant_id=runtime.tenant, principal_type="user", principal_id=actor.user_id)
                    fresh = replace(cached, authorized_workspace_ids=active.workspace_ids,
                        authorized_organization_ids=active.organization_ids, authorized_legal_entity_ids=active.legal_entity_ids)
                    for label, principal in (("cached", cached), ("fresh", fresh)):
                        with server_principal_context(principal):
                            for operation in ("get", "historical-create-replay"):
                                try:
                                    _read(connection, runtime, sale, originals, actor, operation)
                                    violation = kind + ":" + label + ":" + operation
                                    observations.append(violation)
                                    violations.append(violation)
                                except FinancePostingError as refused:
                                    assert "denied" in refused.code
                    raise _RollbackProbe()
            except _RollbackProbe:
                pass
        _preserved(runtime, baseline, "retired-" + kind)
        with runtime.actor("maker") as (connection, _, actor):
            _read(connection, runtime, sale, originals, actor, "get")
            _read(connection, runtime, sale, originals, actor, "historical-create-replay")
    _retain("stock-current-grant-observations.json", {"unexpected_admissions": violations,
        "original_source": sale, "original_commands": originals, "original_66_financial_tables_unchanged": True,
        "coordination_gate_classification": "Exact tenant/pool/cardinality/all other fields; only known version may monotonically advance",
        "persisted_sql_amount_ceiling_proven": False, "fresh_scope_uses_existing_separate_sets": True})
    assert not violations, "Retired original parent authority admitted cached or fresh stock reads: " + ", ".join(violations)


def test_actual_stock_native_capacity_wait_cannot_emit_after_committed_read_permission_retirement(
        receipt_database: tuple[str, str]) -> None:
    runtime, sale = _setup(receipt_database)
    originals = _originals(runtime, sale)
    baseline = _original_tables(runtime)
    with runtime.actor("maker") as (connection, _, actor):
        principal = current_server_principal()
        assert principal is not None
        row = connection.execute("""SELECT location_id,item_id FROM reconforge.stock_sales_orders
            WHERE tenant_id=%s AND id=%s""", (runtime.tenant, sale["id"])).fetchone()
        key = "work|kwd-entity|" + row["location_id"] + "|" + row["item_id"] + "|"
    readers: Queue[int] = Queue()
    revokers: Queue[int] = Queue()
    admitted, release_reader = Event(), Event()

    def reader() -> None:
        with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, **SCOPE) as connection, server_principal_context(principal):
            connection.execute("SET LOCAL statement_timeout='12s'")
            readers.put(connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"])
            assert _read(connection, runtime, sale, originals, actor, "get") == sale
            assert _read(connection, runtime, sale, originals, actor, "historical-create-replay") == originals["create"]["result"]
            admitted.set()
            assert release_reader.wait(timeout=6)

    def revoker() -> None:
        with psycopg.connect(runtime.admin_dsn) as connection:
            connection.execute("SET LOCAL statement_timeout='12s'")
            revokers.put(connection.execute("SELECT pg_backend_pid()").fetchone()[0])
            assert _retire(connection, runtime.tenant, "permission") > 0

    with psycopg.connect(runtime.admin_dsn) as native_holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder_pid = native_holder.execute("SELECT pg_backend_pid()").fetchone()[0]
        native_holder.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (key,))
        read_future = workers.submit(reader)
        try:
            reader_pid = readers.get(timeout=6)
            _wait_on(runtime.admin_dsn, reader_pid, holder_pid)
            revoke_future = workers.submit(revoker)
            revoker_pid = revokers.get(timeout=6)
            _wait_on(runtime.admin_dsn, revoker_pid, reader_pid)
            assert not revoke_future.done()
            native_holder.commit()
            assert admitted.wait(timeout=6)
            assert not revoke_future.done(), "Current authority SHARE pins retirement until the original reader commits."
        finally:
            native_holder.rollback()
            release_reader.set()
        read_future.result(timeout=15)
        revoke_future.result(timeout=15)
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, **SCOPE) as connection, server_principal_context(principal):
        _denied_reads(connection, runtime, sale, originals, actor)
    _preserved(runtime, baseline, "native-capacity-permission-wait")
    _retain("stock-native-capacity-permission-wait.json", {"native_holder_pid": holder_pid, "reader_pid": reader_pid,
        "revoker_pid": revoker_pid, "exact_native_capacity_wait_observed": True, "authority_share_pin_observed": True,
        "retirement_committed_before_source_release": False, "original_get_and_create_replay_completed": True,
        "cached_get_and_create_replay_deny_after_retirement": True, "original_66_financial_tables_unchanged": True,
        "persisted_sql_amount_ceiling_proven": False})


def test_actual_stock_write_threshold_preserves_whole_native_cycle_and_original_effect_amount(
        receipt_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    write = {"sales.manage", "sales.approve", "finance_core.manage", "finance_core.validate", "finance_core.post"}
    maximum = Decimal("20")
    observations = []

    def policy(principal: ServerPrincipal, **context: Any) -> Any:
        if context["required_permission"] in write and context["amount"] is not None:
            observations.append({"permission": context["required_permission"], "amount": str(context["amount"]),
                "maximum": str(maximum)})
            return evaluate_principal_access(principal, maximum_amount=maximum, **context)
        return evaluate_principal_access(principal, **context)

    monkeypatch.setattr(financial_policy, "evaluate_principal_access", policy)
    monkeypatch.setattr(sales_policy, "evaluate_principal_access", policy)
    runtime, sale = _setup(receipt_database)
    originals = _originals(runtime, sale)
    baseline = _original_tables(runtime)
    maximum = Decimal("2")
    with runtime.actor("maker") as (connection, _, actor):
        with pytest.raises(FinancePostingError) as birth:
            _stock(connection, runtime).create(_request("KWD-WRITE-TOO-LOW"), command_id="stock-write-low-birth", actor=actor)
        assert "denied" in birth.value.code
        with pytest.raises(FinancePostingError) as replay:
            _read(connection, runtime, sale, originals, actor, "historical-submit-replay")
        assert "denied" in replay.value.code
        assert _read(connection, runtime, sale, originals, actor, "get") == sale
    maximum = Decimal("20")
    with runtime.actor("maker") as (connection, _, actor):
        _read(connection, runtime, sale, originals, actor, "historical-create-replay")
        _read(connection, runtime, sale, originals, actor, "historical-submit-replay")
    _preserved(runtime, baseline, "write-original-effect-threshold")
    assert observations and all(Decimal(value["amount"]) <= Decimal("3.000") for value in observations)
    _retain("stock-write-original-effect-threshold.json", {"observations": observations,
        "complete_paid_source_and_four_native_effects_under_write_cap20": True,
        "write_cap2_denies_original3_amount": True, "uncapped_read_price_minor": 3000000,
        "original_source": sale, "original_commands": originals, "original_66_financial_tables_unchanged": True,
        "persisted_sql_amount_ceiling_proven": False})


def test_actual_stock_cached_actor_rechecks_all_seven_persisted_retirement_classes(
        receipt_database: tuple[str, str]) -> None:
    runtime, sale = _setup(receipt_database)
    originals = _originals(runtime, sale)
    baseline = _original_tables(runtime)
    with runtime.actor("maker") as (_, _, actor):
        principal = current_server_principal()
        assert principal is not None
    observations = []
    for kind in ("human", "assignment", "role", "permission", "workspace", "organization", "legal_entity"):
        with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, **SCOPE) as connection:
            try:
                with connection.transaction():
                    retired = _retire(connection, runtime.tenant, kind)
                    assert retired > 0
                    with server_principal_context(principal):
                        _denied_reads(connection, runtime, sale, originals, actor)
                    observations.append({"retirement": kind, "persisted_rows_retired": retired,
                        "all_four_cached_read_and_replay_paths_denied": True})
                    raise _RollbackProbe()
            except _RollbackProbe:
                pass
        _preserved(runtime, baseline, "seven-retirement-" + kind)
        with runtime.actor("maker") as (connection, _, actor):
            assert _read(connection, runtime, sale, originals, actor, "get") == sale
    _retain("stock-seven-persisted-retirement-observations.json", {"observations": observations,
        "original_source": sale, "original_commands": originals,
        "original_66_financial_tables_unchanged": True, "persisted_sql_amount_ceiling_proven": False})


@pytest.mark.parametrize("kind", ["permission", "legal_entity"])
def test_actual_stock_retirement_first_reader_waits_before_source_and_denies(
        receipt_database: tuple[str, str], kind: str) -> None:
    runtime, sale = _setup(receipt_database)
    originals = _originals(runtime, sale)
    baseline = _original_tables(runtime)
    with runtime.actor("maker") as (_, _, actor):
        principal = current_server_principal()
        assert principal is not None
    started: Queue[int] = Queue()

    def reader() -> None:
        with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, **SCOPE) as connection, server_principal_context(principal):
            connection.execute("SET LOCAL statement_timeout='12s'")
            started.put(connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"])
            _denied_reads(connection, runtime, sale, originals, actor)

    with psycopg.connect(runtime.admin_dsn) as revoker, ThreadPoolExecutor(max_workers=1) as workers:
        revoker_pid = revoker.execute("SELECT pg_backend_pid()").fetchone()[0]
        if kind == "permission":
            assert revoker.execute("""SELECT permission_name FROM reconforge.identity_role_permissions
                WHERE tenant_id=%s AND permission_name='finance_core.read' AND active FOR UPDATE""",
                (runtime.tenant,)).fetchall()
        else:
            assert revoker.execute("""SELECT id FROM reconforge.principal_scope_grants
                WHERE tenant_id=%s AND id='kwd-maker-legal_entity' AND revoked_at IS NULL FOR UPDATE""",
                (runtime.tenant,)).fetchone()
        future = workers.submit(reader)
        try:
            reader_pid = started.get(timeout=6)
            _wait_on(runtime.admin_dsn, reader_pid, revoker_pid)
            # A queued authority admission must not own the immutable source.
            with psycopg.connect(runtime.admin_dsn) as probe:
                assert probe.execute("""SELECT id FROM reconforge.stock_sales_orders
                    WHERE tenant_id=%s AND id=%s FOR UPDATE NOWAIT""", (runtime.tenant, sale["id"])).fetchone()
            assert _retire(revoker, runtime.tenant, kind) > 0
        finally:
            revoker.commit()
        future.result(timeout=15)
    _preserved(runtime, baseline, "retirement-first-" + kind)
    _retain("stock-native-retirement-first-" + kind + ".json", {"retirement": kind,
        "reader_pid": reader_pid, "revoker_pid": revoker_pid, "exact_authority_blocking_edge_observed": True,
        "source_update_nowait_succeeded_before_retirement_commit": True,
        "all_four_cached_read_and_replay_paths_denied_after_commit": True,
        "original_source": sale, "original_commands": originals, "original_66_financial_tables_unchanged": True})


def test_actual_two_line_commerce_get_requires_each_original_line_price_context(
        receipt_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, sale = _setup(receipt_database)
    _originals(runtime, sale)
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresStockCommerceRepository(connection, runtime.tenant, **SCOPE,
            organization_code="ORG", entity_code="ENTITY-KWD")
        acknowledgement = owner.create(CommercialOrder("KWD_TWO_LINES", "KWD_CUSTOMER", "SYNTHETIC", "KWD", "2026-10-09", (
            CommercialLine("KWD_ITEM", "KWD_MAIN", "STOCK", "0.001", 3000000, "Original first fractional line"),
            CommercialLine("KWD_ITEM", "KWD_MAIN", "STOCK", "0.001", 3000000, "Original second fractional line"))),
            command_id="kwd-two-line-original-create", actor=actor)
        result = owner.get(acknowledgement["id"], actor=actor)
    assert "lines" not in acknowledgement and result["total_minor"] == "6000"
    assert len(result["lines"]) == 2 and all(line["source"]["unit_price_minor"] == "3000000" for line in result["lines"])
    baseline = _original_tables(runtime)
    selected, maximum = "finance_core.read", Decimal("20")
    observations = []

    def financial(principal: ServerPrincipal, **context: Any) -> Any:
        if context["required_permission"] == selected:
            observations.append({"permission": selected,
                "amount": str(context["amount"]) if context["amount"] is not None else None,
                "maximum": str(maximum)})
            return evaluate_principal_access(principal, maximum_amount=maximum, **context)
        return evaluate_principal_access(principal, **context)

    def sales(principal: ServerPrincipal, **context: Any) -> Any:
        if context["required_permission"] == selected and context["amount"] is not None:
            return evaluate_principal_access(principal, maximum_amount=maximum, **context)
        return evaluate_principal_access(principal, **context)

    monkeypatch.setattr(financial_policy, "evaluate_principal_access", financial)
    monkeypatch.setattr(sales_policy, "evaluate_principal_access", sales)
    for permission in sorted(READ):
        selected, maximum = permission, Decimal("20")
        with runtime.actor("maker") as (connection, _, actor):
            owner = PostgresStockCommerceRepository(connection, runtime.tenant, **SCOPE,
                organization_code="ORG", entity_code="ENTITY-KWD")
            with pytest.raises(FinancePostingError) as denied:
                owner.get(acknowledgement["id"], actor=actor)
            assert "denied" in denied.value.code
        maximum = Decimal("4000")
        with runtime.actor("maker") as (connection, _, actor):
            owner = PostgresStockCommerceRepository(connection, runtime.tenant, **SCOPE,
                organization_code="ORG", entity_code="ENTITY-KWD")
            assert owner.get(acknowledgement["id"], actor=actor) == result
        _preserved(runtime, baseline, "commerce-price-" + permission)
    assert any(value["amount"] == "3000.000" for value in observations)
    _retain("stock-commerce-original-two-line-read-context.json", {"observations": observations,
        "original_header_acknowledgement": acknowledgement, "original_complete_get": result,
        "parent_total_minor": 6000, "original_line_unit_price_minor": 3000000, "currency_precision": 3,
        "each_of_four_read_caps20_denied_caps4000_allowed": True, "header_ack_exposes_no_lines": True,
        "original_66_financial_tables_unchanged": True, "persisted_sql_amount_ceiling_proven": False,
        "private_tranche_cogs_amount_not_publicly_exposed": True})


def test_actual_currency_precision_sql_change_is_specific_native_integrity_refusal(
        receipt_database: tuple[str, str]) -> None:
    runtime, sale = _setup(receipt_database)
    originals = _originals(runtime, sale)
    baseline = _original_tables(runtime)
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, **SCOPE) as connection:
        before = connection.execute("""SELECT to_jsonb(c)::text original FROM reconforge.currencies c
            WHERE tenant_id=%s AND code='KWD'""", (runtime.tenant,)).fetchone()["original"]
        with pytest.raises(psycopg.errors.RaiseException) as rejected, connection.transaction():
            connection.execute("UPDATE reconforge.currencies SET minor_units=2 WHERE tenant_id=%s AND code='KWD'",
                (runtime.tenant,))
        assert rejected.value.sqlstate == "P0001"
        assert rejected.value.diag.message_primary == "Currency code and precision are immutable; create an explicit new policy instead."
        assert rejected.value.diag.constraint_name is None
        after = connection.execute("""SELECT to_jsonb(c)::text original FROM reconforge.currencies c
            WHERE tenant_id=%s AND code='KWD'""", (runtime.tenant,)).fetchone()["original"]
        assert before == after
    with runtime.actor("maker") as (connection, _, actor):
        assert _read(connection, runtime, sale, originals, actor, "get") == sale
        assert _read(connection, runtime, sale, originals, actor, "historical-create-replay") == originals["create"]["result"]
    _preserved(runtime, baseline, "specific-currency-precision-refusal")
    _retain("stock-currency-precision-native-refusal.json", {"sqlstate": "P0001",
        "message_primary": rejected.value.diag.message_primary, "constraint_name": None,
        "original_currency_row": before, "retained_currency_row": after,
        "original_source": sale, "original_commands": originals, "original_66_financial_tables_unchanged": True,
        "changed_live_master_replay_proven": False, "interpretation": "Native integrity refused the precision change; no changed-master replay occurred."})
