"""Pure boundaries of fixed source discovery, authority and parent lock order.

These checks exercise adapters as a system under test. They do not replace
native RLS, SQL closure, finance effects or migration evidence.
"""

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.monetary_customer_returns import MonetaryHistory, apply_monetary_event, prepare_monetary_event
from reconforge.infrastructure.postgres_monetary_customer_partial_returns import (
    PostgresMonetaryCustomerPartialReturnsRepository,
)
from reconforge.infrastructure.postgres_monetary_stock_sales import (
    OPERATION_PERMISSIONS,
    READ,
    VALUATION_PERMISSIONS,
    PostgresMonetaryStockSalesRepository,
    _StockFxOwner,
    book_carrying,
    native_child_command,
)
from reconforge.infrastructure.postgres_operational_fx_tax import PostgresOperationalFxTaxRepository
from reconforge.infrastructure.postgres_stock_sales import OPERATION_PERMISSIONS as LEGACY_PERMISSIONS
from reconforge.infrastructure.postgres_stock_sales import PostgresStockSalesRepository
from tests.test_monetary_customer_returns import DAY, original, rate


def policy(currency: str, precision: int) -> dict[str, Any]:
    return {"currency_code": currency, "precision": precision, "rounding_policy": "ROUND_HALF_UP",
            "registry_version": "1", "registry_digest": "a" * 64}


def source_row() -> dict[str, Any]:
    return {"id": "stock", "customer_id": "customer", "invoice_id": "invoice", "status": "Invoiced", "source": {
        "schema_version": "stock-sales-monetary-order-v2", "total_minor": 500, "unit_price_minor": 1000, "net_unit_price_minor": 500,
        "monetary_policy": policy("EUR", 2), "functional_policy": policy("KWD", 3)},
        "issue_plan": {"total_cost_minor": 7}}


def test_delegated_cash_prepare_and_review_require_real_receivables_rights() -> None:
    assert OPERATION_PERMISSIONS["prepare-collection"] == LEGACY_PERMISSIONS["prepare-collection"] | {"receivables.manage"}
    assert OPERATION_PERMISSIONS["review-collection"] == LEGACY_PERMISSIONS["review-collection"] | {"receivables.approve"}
    for name in set(LEGACY_PERMISSIONS) - {"prepare-collection", "review-collection"}:
        assert OPERATION_PERMISSIONS[name] == LEGACY_PERMISSIONS[name]
    assert "receivables.manage" not in LEGACY_PERMISSIONS["prepare-collection"]
    assert "receivables.approve" not in LEGACY_PERMISSIONS["review-collection"]


@pytest.mark.parametrize("operation", ["read", "prepare-invoice"])
def test_foreign_price_and_functional_cost_authority_are_never_mixed_or_maximized(
    operation: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = object.__new__(PostgresMonetaryStockSalesRepository)
    owner.scope = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
    calls: list[tuple[int, int, bool, bool]] = []

    def authorize(actor: Any, permission: str, scope: dict[str, Any], *, mutation: bool, allow_zero_amount: bool) -> None:
        calls.append((scope["amount_minor"], scope["currency_precision"], mutation, allow_zero_amount))

    owner.ops = SimpleNamespace(_actor=authorize)  # type: ignore[assignment]
    owner.connection = SimpleNamespace(execute=lambda *args: None)
    monkeypatch.setattr(owner, "_authority_locks", lambda *args, **kwargs: None)
    monkeypatch.setattr(owner, "_origin", lambda identifier: None)
    owner._actor(PostingActor("actor", "human", frozenset()), operation, source_row())
    assert {(amount, precision) for amount, precision, _, _ in calls} == ({(1000, 2), (7, 3)} if operation == "read" else {(1000, 2), (500, 2), (7, 3)})
    assert all(mutation == (operation != "read") and not allow_zero for _, _, mutation, allow_zero in calls)


def test_known_original_gross_is_authorized_in_each_currency_before_later_phases(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = object.__new__(PostgresMonetaryStockSalesRepository)
    owner.scope = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
    calls = []
    owner.ops = SimpleNamespace(_actor=lambda actor, permission, scope, **kwargs: calls.append((scope["amount_minor"], scope["currency_precision"])))  # type: ignore[assignment]
    owner.connection = SimpleNamespace(execute=lambda *args: None)
    monkeypatch.setattr(owner, "_authority_locks", lambda *args, **kwargs: None)
    monkeypatch.setattr(owner, "_origin", lambda identifier: {"payload": {"equation": {"foreign_gross_minor": 570, "functional_gross_minor": 7777}},
        "ar_balance": {"functional_outstanding_minor": "10000"}})
    owner._actor(PostingActor("actor", "human", frozenset()), "prepare-invoice", source_row())
    assert set(calls) == {(1000, 2), (570, 2), (10000, 3), (7, 3)}


@pytest.mark.parametrize("value", [None, True, 1, "01", "1.0", "1e3", "-1", "١", "9" * 5000, "9000000000000000001"])
def test_book_carrying_refuses_noncanonical_or_unbounded_exposure(value: Any) -> None:
    with pytest.raises(FinancePostingError):
        book_carrying({"ar_balance": {"functional_outstanding_minor": value}})


def test_book_carrying_and_child_keys_preserve_zero_and_full_public_command_range() -> None:
    assert book_carrying({"ar_balance": {"functional_outstanding_minor": "0"}}) == 0
    assert book_carrying({"ar_balance": {"functional_outstanding_minor": "9000000000000000000"}}) == 9000000000000000000
    command = "a" * 140
    first = native_child_command("stock-invoice", command)
    assert len(first) <= 140 and first == native_child_command("stock-invoice", command)
    assert first != native_child_command("stock-cash", command)
    assert first != native_child_command("stock-invoice", command[:-1] + "b")


@pytest.mark.parametrize("share", [False, True])
def test_all_detail_and_mutation_paths_lock_customer_then_invoice_then_stock(share: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = object.__new__(PostgresMonetaryStockSalesRepository)
    owner.tenant_id = "tenant"
    calls = []
    owner.connection = SimpleNamespace(execute=lambda sql, args: calls.append((sql, args)))
    monkeypatch.setattr(owner, "_order", lambda identifier, **kwargs: calls.append(("stock", kwargs)))
    owner._parents(source_row(), share=share)
    assert "ar_customers" in calls[0][0] and calls[0][1] == ("tenant", "customer")
    assert "ar_invoices" in calls[1][0] and calls[1][1] == ("tenant", "invoice")
    assert calls[2] == ("stock", {"lock": not share, "read_lock": share})
    assert all(("FOR SHARE" if share else "FOR UPDATE") in calls[index][0] for index in (0, 1))


@pytest.mark.parametrize("schema", ["stock-sales-monetary-order-v2", None, "stock-sales-order-v0"])
def test_old_stock_getter_refuses_new_or_unclassified_source_before_command_admission(schema: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = object.__new__(PostgresStockSalesRepository)
    owner.tenant_id = "tenant"
    owner.scope = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
    monkeypatch.setattr(owner, "_one", lambda *args: {"source": {"schema_version": schema}})
    with pytest.raises(FinancePostingError) as caught:
        owner._order("stock")
    assert caught.value.code == "stock_sales_protocol_conflict"


def test_old_fx_source_getter_refuses_monetary_stock_owner_before_parent_wait() -> None:
    owner = object.__new__(PostgresOperationalFxTaxRepository)
    owner.tenant_id = "tenant"
    cursor = SimpleNamespace(description=[SimpleNamespace(name="payload")], fetchall=lambda: [
        {"payload": {"schema_version": "operational-fx-stock-source-v2"}}])
    owner.connection = SimpleNamespace(execute=lambda *args: cursor)
    with pytest.raises(FinancePostingError) as caught:
        owner._peek("source", "fx-source")
    assert caught.value.code == "fx_source_protocol_conflict"


def test_default_foreign_owner_denies_nullable_journal_before_any_phase_mutation() -> None:
    owner = object.__new__(PostgresOperationalFxTaxRepository)
    for source_schema in ("operational-fx-source-v1", "operational-fx-stock-source-v2"):
        with pytest.raises(FinancePostingError) as caught:
            owner._admit_journal_presence({"schema_version": source_schema}, {"entry_id": None, "amount_minor": 0})
        assert caught.value.code == "fx_state_invalid"


def zero_collection(monkeypatch: pytest.MonkeyPatch) -> tuple[_StockFxOwner, dict[str, Any], dict[str, Any], MonetaryHistory]:
    source = original(amount=2, exchange="0.5", quantity=3, cost=0, tax=None)
    history = MonetaryHistory(source)
    first = prepare_monetary_event(history, "Collection", posting_date=DAY, amount_minor=1, settlement_rate=rate("0.5"))
    history = apply_monetary_event(history, first)
    pending = prepare_monetary_event(history, "Collection", posting_date=DAY, amount_minor=1, settlement_rate=rate("0.000001"))
    assert pending.monetary.functional_turnover_minor == 0
    owner = object.__new__(_StockFxOwner)
    owner.tenant_id = "tenant"
    owner.stock = SimpleNamespace(_origin=lambda identifier: {"id": "origin", "fx_source_id": "fx", "invoice_id": "invoice"},
                                  _history=lambda identifier: history)  # type: ignore[assignment]
    monkeypatch.setattr(owner, "_state", lambda source: {"active_revaluation_plan_id": None})
    from dataclasses import asdict
    native_source = {"id": "fx", "schema_version": "operational-fx-stock-source-v2", "stock_order_id": "stock", "invoice_id": "invoice"}
    plan = {"id": "FX1-" + "a" * 32, "schema_version": "operational-fx-stock-plan-v2", "kind": "settle", "source_id": "fx",
        "entry_id": None, "amount_minor": 0, "snapshot": None, "validation_digest": None, "posting_date": DAY,
        "equation": {"foreign_minor": 1, "monetary_event": asdict(pending), "lines": []}}
    return owner, native_source, plan, history


def test_new_fixed_owner_allows_only_proved_zero_local_foreign_cash_without_journal(monkeypatch: pytest.MonkeyPatch) -> None:
    owner, source, plan, _ = zero_collection(monkeypatch)
    owner._admit_journal_presence(source, plan)


def test_new_zero_collection_refuses_active_closing_valuation_before_review_or_post(monkeypatch: pytest.MonkeyPatch) -> None:
    owner, source, plan, _ = zero_collection(monkeypatch)
    monkeypatch.setattr(owner, "_state", lambda source: {"active_revaluation_plan_id": "FX1-" + "c" * 32})
    with pytest.raises(FinancePostingError) as caught:
        owner._admit_journal_presence(source, plan)
    assert caught.value.code == "stock_monetary_state_conflict"


@pytest.mark.parametrize("changed", ["legacy", "recognize", "boolean", "fake_snapshot", "fake_line", "foreign_zero", "functional_cash"])
def test_zero_journal_has_no_legacy_missing_or_balanced_foreign_source_fallback(changed: str, monkeypatch: pytest.MonkeyPatch) -> None:
    owner, source, plan, _ = zero_collection(monkeypatch)
    if changed == "legacy":
        source["schema_version"] = "operational-fx-source-v1"
    elif changed == "recognize":
        plan["kind"] = "recognize"
    elif changed == "boolean":
        plan["amount_minor"] = False
    elif changed == "fake_snapshot":
        plan["snapshot"] = {}
    elif changed == "fake_line":
        plan["equation"]["lines"] = [{"debit_minor": 0, "credit_minor": 0}]
    elif changed == "foreign_zero":
        plan["equation"]["foreign_minor"] = 0
    else:
        plan["equation"]["monetary_event"]["monetary"]["functional_cash_minor"] = 1
    with pytest.raises(FinancePostingError):
        owner._admit_journal_presence(source, plan)


def test_retained_zero_ack_must_pin_its_native_history_member_and_can_survive_later_closing_valuation(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import asdict
    owner, source, plan, history = zero_collection(monkeypatch)
    pending = prepare_monetary_event(history, "Collection", posting_date=DAY, amount_minor=1, settlement_rate=rate("0.000001"))
    history = apply_monetary_event(history, pending)
    monkeypatch.setattr(owner.stock, "_history", lambda identifier: history)
    monkeypatch.setattr(owner, "_state", lambda source: {"active_revaluation_plan_id": "FX1-" + "c" * 32})
    calls = []
    def execute(sql: str, args: tuple[Any, ...]) -> Any:
        calls.append(args)
        return SimpleNamespace(fetchone=lambda: (1,))
    owner.connection = SimpleNamespace(execute=execute)
    owner._admit_journal_presence(source, plan)
    assert calls == [("tenant", "origin", 2, plan["id"])]
    assert plan["equation"]["monetary_event"] == asdict(pending)
    owner.connection = SimpleNamespace(execute=lambda sql, args: SimpleNamespace(fetchone=lambda: None))
    with pytest.raises(FinancePostingError):
        owner._admit_journal_presence(source, plan)


@pytest.mark.parametrize("field", ["equation", "monetary_event", "monetary"])
@pytest.mark.parametrize("malformed", [None, [], "malformed", False])
def test_malformed_zero_collection_objects_have_stable_native_refusal(
    field: str, malformed: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, source, plan, _ = zero_collection(monkeypatch)
    if field == "equation":
        plan[field] = malformed
    elif field == "monetary_event":
        plan["equation"][field] = malformed
    else:
        plan["equation"]["monetary_event"][field] = malformed
    with pytest.raises(FinancePostingError) as caught:
        owner._admit_journal_presence(source, plan)
    assert caught.value.code == "stock_monetary_evidence_invalid"


@pytest.mark.parametrize("kind", ["recognize", "settle", "revalue", "reverse_revaluation"])
def test_every_posted_fx_phase_refreshes_the_owned_projection_without_reapplying_cash(kind: str) -> None:
    owner = object.__new__(_StockFxOwner)
    owner.tenant_id = "tenant"
    calls = []
    owner.connection = SimpleNamespace(execute=lambda query, args: calls.append((query, args)))
    owner._after_posted({"stock_order_id": "stock"}, {"id": "FX1-plan", "kind": kind, "equation": {"monetary_event": {"sequence": 1}}})
    assert len(calls) == (2 if kind == "settle" else 1)
    assert "monetary_stock_refresh_balance" in calls[-1][0] and calls[-1][1] == ("tenant", "stock")
    if kind == "settle":
        assert "monetary_stock_append_collection" in calls[0][0]
        assert calls[0][1] == ("tenant", "stock", "FX1-plan", '{"sequence":1}')


@pytest.mark.parametrize("origin_exists", [False, True])
def test_pending_native_fx_plan_publishes_only_existing_origin_pending_identity(origin_exists: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = object.__new__(_StockFxOwner)
    owner.tenant_id = "tenant"
    calls = []
    owner.connection = SimpleNamespace(execute=lambda query, args: calls.append((query, args)))
    owner.stock = SimpleNamespace(_origin=lambda identifier: {"id": "origin"} if origin_exists else None)  # type: ignore[assignment]
    expected = {"id": "new-plan"}
    monkeypatch.setattr(PostgresOperationalFxTaxRepository, "_prepare", lambda *args, **kwargs: expected)
    assert owner._prepare({"stock_order_id": "stock"}, kind="recognize", equation={"lines": [{"debit_minor": 1}]},
        period_id="period", posting_date=DAY, reason="New native phase", sequence=0, request={}, command_id="command", digest="a" * 64,
        actor=PostingActor("actor", "human", frozenset())) is expected
    assert len(calls) == int(origin_exists)
    if origin_exists:
        assert "monetary_stock_refresh_balance" in calls[0][0] and calls[0][1] == ("tenant", "stock")


@pytest.mark.parametrize("total", [7, 7000])
def test_prospective_issue_authorizes_actual_functional_cost_separately_before_claim_birth(total: int, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = object.__new__(PostgresMonetaryStockSalesRepository)
    owner.scope = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
    calls = []
    owner.ops = SimpleNamespace(_actor=lambda actor, permission, scope, **kwargs: calls.append((scope["amount_minor"], scope["currency_precision"])))  # type: ignore[assignment]
    owner.connection = SimpleNamespace(execute=lambda *args: None)
    monkeypatch.setattr(owner, "_authority_locks", lambda *args: None)
    monkeypatch.setattr(owner, "_origin", lambda identifier: None)
    row = source_row()
    row["issue_plan"] = None
    owner._issue_authority(row, total, None, PostingActor("actor", "human", frozenset()))
    assert set(calls) == {(1000, 2), (500, 2), (total, 3)}


@pytest.mark.parametrize("cost", [False, -1, 0])
def test_prospective_zero_issue_has_no_missing_native_evidence_or_boolean_cost_fallback(cost: Any) -> None:
    owner = object.__new__(PostgresMonetaryStockSalesRepository)
    with pytest.raises(FinancePostingError) as caught:
        owner._issue_authority(source_row(), cost, None, PostingActor("actor", "human", frozenset()))
    assert caught.value.code == "stock_monetary_evidence_invalid"


@pytest.mark.parametrize("operation", ["get", "balance"])
def test_partial_public_reads_pin_parent_prefix_and_recheck_book_authority_after_wait(
    operation: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = object.__new__(PostgresMonetaryCustomerPartialReturnsRepository)
    owner.tenant_id = "tenant"
    owner.owner = SimpleNamespace(_transaction=nullcontext)
    calls: list[Any] = []
    origin = {"id": "origin", "stock_order_id": "stock", "invoice_id": "invoice",
              "workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity", "book": 700}
    current_origin = {**origin, "book": 840}
    row = {"source": {"schema_version": "stock-sales-monetary-order-v2"}, "invoice_id": "invoice"}
    held = False

    def parents(actual: Any, *, share: bool) -> None:
        nonlocal held
        assert actual is row and share
        held = True
        calls.append("customer/invoice/stock SHARE")

    stock = SimpleNamespace(_order=lambda identifier: row, _parents=parents)
    owner.connection = SimpleNamespace(execute=lambda query, args: calls.append("close"))
    owner.legacy = SimpleNamespace(_authority_locks=lambda *args: calls.append("scope authority"))
    monkeypatch.setattr(owner, "_plan_authority", lambda *args: calls.append("plan authority"))
    monkeypatch.setattr(owner, "_stock", lambda actual: stock)
    monkeypatch.setattr(owner, "_row", lambda identifier: {"source_id": "origin"})
    monkeypatch.setattr(owner, "_origin", lambda identifier: current_origin if held else origin)
    monkeypatch.setattr(owner, "_actor", lambda actor, name, actual: calls.append(("book authority", actual["book"])))
    monkeypatch.setattr(owner, "_view", lambda identifier: calls.append("view") or {"id": identifier})

    def one(query: str, args: Any) -> dict[str, Any]:
        if "SELECT * FROM" in query:
            assert not held
            return origin
        assert held
        calls.append("view")
        return {"value": {"id": "stock"}}

    monkeypatch.setattr(owner, "_one", one)
    actor = PostingActor("actor", "human", frozenset())
    if operation == "get":
        assert owner.get("plan", actor=actor) == {"id": "plan"}
    else:
        assert owner.balance("stock", origin, actor=actor) == {"id": "stock"}
    assert calls == ["plan authority" if operation == "get" else "scope authority",
                     ("book authority", 700), "customer/invoice/stock SHARE", ("book authority", 840), "close", "view"]


class AuthorityCursor:
    description: list[Any] = []

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


def locked_authority_owner(monkeypatch: pytest.MonkeyPatch, *, missing_reverse: bool = False) -> tuple[Any, PostingActor, list[Any]]:
    """Run the real authority lock path; only PostgreSQL transport is synthetic."""
    import reconforge.infrastructure.postgres_stock_sales as legacy

    owner = object.__new__(PostgresMonetaryStockSalesRepository)
    owner.tenant_id = "tenant"
    owner.scope = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
    permissions = frozenset().union(*OPERATION_PERMISSIONS.values(), *VALUATION_PERMISSIONS.values())
    actor = PostingActor("actor", "human", permissions, step_up_active=True)
    calls: list[Any] = []
    principal = SimpleNamespace(user=SimpleNamespace(id=actor.user_id, username=actor.username, disabled=False),
                                principal_type="user", step_up_active=True)
    monkeypatch.setattr(legacy, "current_server_principal", lambda: principal)
    owner.authority = SimpleNamespace(_actor=lambda actual, permission, **kwargs: calls.append(("policy", permission, kwargs)))

    def execute(query: str, args: Any) -> AuthorityCursor:
        calls.append(("query", query, args))
        if "identity_users" in query:
            return AuthorityCursor([{"id": actor.user_id}])
        if "identity_user_roles" in query:
            return AuthorityCursor([{"permission_name": permission} for permission in args[2]
                if not (missing_reverse and permission == "finance_core.reverse")])
        if "SELECT DISTINCT scope_type" in query:
            return AuthorityCursor([{"scope_type": "workspace"}, {"scope_type": "organization"}, {"scope_type": "legal_entity"}])
        if "principal_scope_grants" in query:
            return AuthorityCursor([{"scope_type": kind, "scope_id": owner.scope[field]} for kind, field in
                (("workspace", "workspace_id"), ("organization", "organization_id"), ("legal_entity", "legal_entity_id"))])
        return AuthorityCursor([])

    owner.connection = SimpleNamespace(execute=execute)
    return owner, actor, calls


@pytest.mark.parametrize("permissions", [*VALUATION_PERMISSIONS.values(),
    VALUATION_PERMISSIONS["review"] | {"finance_core.reverse"},
    VALUATION_PERMISSIONS["post"] | {"finance_core.reverse"}])
def test_declared_valuation_unions_reach_all_current_authority_locks(permissions: frozenset[str], monkeypatch: pytest.MonkeyPatch) -> None:
    owner, actor, calls = locked_authority_owner(monkeypatch)
    owner._authority_locks(actor, "read", permissions=permissions)
    assert {call[1] for call in calls if call[0] == "policy"} == permissions
    queries = [call for call in calls if call[0] == "query"]
    assert len(queries) == 4
    assert all("FOR SHARE" in queries[index][1] for index in (0, 1, 3))
    assert set(queries[1][2][2]) == permissions
    assert "revoked_at IS NULL" in queries[3][1]


def test_real_inverse_authority_reaches_source_and_actor_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    owner, actor, calls = locked_authority_owner(monkeypatch)
    monkeypatch.setattr(owner, "_order", lambda identifier: {"id": identifier})
    monkeypatch.setattr(owner, "_actor", lambda actual, operation, row: calls.append(("source authority", actual, operation, row)))
    monkeypatch.setattr(owner, "_origin", lambda identifier: {"id": "origin"})
    assert owner._valuation_authority("stock", actor, "prepare_reversal") == {"id": "origin"}
    assert any(call[:2] == ("policy", "finance_core.reverse") for call in calls)
    assert any(call[0] == "source authority" for call in calls)
    assert any(call[0] == "query" and "app.stock_sales_actor_id" in call[1] for call in calls)


def test_inverse_declared_union_does_not_bypass_persisted_reverse_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    owner, actor, calls = locked_authority_owner(monkeypatch, missing_reverse=True)
    with pytest.raises(FinancePostingError) as caught:
        owner._authority_locks(actor, "read", permissions=VALUATION_PERMISSIONS["prepare_reversal"])
    assert caught.value.code == "sales_actor_denied"
    assert any(call[:2] == ("policy", "finance_core.reverse") for call in calls)
    assert len([call for call in calls if call[0] == "query"]) == 2


@pytest.mark.parametrize(("operation", "permissions"), [
    ("read", READ - {"sales.read"}), ("read", READ | {"unregistered.permission"}),
    ("read", frozenset().union(*VALUATION_PERMISSIONS.values())),
    ("read", set(VALUATION_PERMISSIONS["prepare_reversal"])),
    ("read", tuple(VALUATION_PERMISSIONS["prepare_reversal"])),
    ("reserve", VALUATION_PERMISSIONS["prepare_reversal"]),
    ("unknown", READ), ("prepare-collection", LEGACY_PERMISSIONS["prepare-collection"]),
])
def test_unregistered_incomplete_wrong_type_or_cross_operation_union_refuses_before_queries(operation: str, permissions: Any) -> None:
    owner = object.__new__(PostgresMonetaryStockSalesRepository)
    with pytest.raises(FinancePostingError) as caught:
        owner._authority_locks(PostingActor("actor", "human", frozenset()), operation, permissions=permissions)
    assert caught.value.code == "sales_actor_denied"


def test_legacy_union_boundary_remains_exact_and_never_admits_reverse() -> None:
    owner = object.__new__(PostgresStockSalesRepository)
    allowed = frozenset().union(*LEGACY_PERMISSIONS.values())
    for operation in ["read", "unknown", *LEGACY_PERMISSIONS]:
        default = LEGACY_PERMISSIONS.get(operation, READ)
        for selected in (default, allowed, default - {"sales.read"}, default | {"finance_core.reverse"}):
            assert owner._permission_union_allowed(operation, selected) == (default <= selected <= allowed)
