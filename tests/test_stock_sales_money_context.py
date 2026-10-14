"""Stock quote disclosure and business effect retain distinct exact contexts."""
from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from reconforge.auth.models import LocalUser
from reconforge.auth.policy import evaluate_principal_access
from reconforge.domain.finance_posting import FinancePostingError, PostingActor, canonical_json, digest_payload
from reconforge.domain.operational_finance import exact_minor_text
from reconforge.domain.stock_commerce import CommercialLine, CommercialOrder
from reconforge.domain.stock_sales import StockOrder
from reconforge.infrastructure.postgres_stock_commerce import (
    COMMERCE_PERMISSIONS,
    PostgresStockCommerceRepository,
    stock_commerce_read_context,
)
from reconforge.infrastructure.postgres_stock_sales import (
    OPERATION_PERMISSIONS,
    READ,
    PostgresStockSalesRepository,
    stock_sales_money_context,
)
from reconforge.platform.common import ServerPrincipal, server_principal_context

SCOPE = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity",
         "organization_code": "ORG", "entity_code": "ENTITY"}


def row() -> dict[str, Any]:
    policy = {"currency_code": "KWD", "precision": 3, "rounding_policy": "ROUND_HALF_UP",
              "registry_version": "synthetic-v1", "registry_digest": "a" * 64}
    return {"currency_code": "KWD", "total_minor": 3000,
        "source": {"currency_code": "KWD", "total_minor": 3000, "unit_price_minor": 3000000,
                   "net_unit_price_minor": 3000000, "monetary_policy": policy, "quantity": "0.001", "quantity_scaled": 1},
        "issue_plan": {"total_cost_minor": 1, "currency_policy": deepcopy(policy),
                       "allocations": [{"remaining_value_minor": 1000, "value_minor": 1}]}}


def repository(connection: Any) -> PostgresStockSalesRepository:
    return PostgresStockSalesRepository(connection, "tenant", **SCOPE)


def test_actual_fractional_price_context_is_exact_and_source_is_unchanged() -> None:
    original = row()
    before = canonical_json(original)
    read, write = stock_sales_money_context(original)
    assert (Decimal(exact_minor_text(read, 3)), Decimal(exact_minor_text(write, 3))) == (Decimal("3000.000"), Decimal("3.000"))
    assert canonical_json(original) == before


@pytest.mark.parametrize("member", ["unit_price_minor", "net_unit_price_minor"])
def test_gross_and_net_price_each_independently_require_full_read_authority(member: str) -> None:
    original = row()
    original["source"][member] = 4000000
    assert stock_sales_money_context(original) == (4000000, 3000)


def test_below_cost_and_temporary_issue_context_preserve_existing_business_thresholds() -> None:
    original = row()
    original["source"].update(unit_price_minor=1000, net_unit_price_minor=1000, total_minor=5000)
    original["total_minor"] = 5000
    original["issue_plan"]["total_cost_minor"] = 6000
    assert stock_sales_money_context(original) == (6000, 6000)
    original["issue_plan"] = None
    original["total_minor"] = 6000
    assert stock_sales_money_context(original) == (6000, 6000)


def test_unexposed_layer_values_quantities_and_metadata_do_not_raise_any_threshold() -> None:
    original = row()
    original.update(row_version=9000000000000000000, unrelated_number=9000000000000000000)
    original["source"].update(quantity_scaled=9000000000000000000, discount_basis_points=9999)
    original["issue_plan"]["allocations"][0]["remaining_value_minor"] = 9000000000000000000
    assert stock_sales_money_context(original) == (3000000, 3000)


@pytest.mark.parametrize("value", [True, 1.1, "3000000", None, 0, -1, 9000000000000000001])
def test_quote_price_never_coerces_missing_or_malformed_money(value: object) -> None:
    original = row()
    original["source"]["unit_price_minor"] = value
    with pytest.raises(FinancePostingError, match="Retained prices"):
        stock_sales_money_context(original)


@pytest.mark.parametrize("field,value", [("precision", 2), ("precision", True), ("currency_code", "USD"),
                                        ("rounding_policy", "ROUND_DOWN"), ("registry_version", "changed"), ("registry_digest", "b" * 64)])
def test_issue_and_quote_require_exact_captured_policy_affinity(field: str, value: object) -> None:
    original = row()
    original["issue_plan"]["currency_policy"][field] = value
    with pytest.raises(FinancePostingError, match="Retained prices"):
        stock_sales_money_context(original)


def test_only_pre_birth_request_may_lack_captured_policy() -> None:
    original = row()
    raw = {key: value for key, value in original["source"].items() if key != "monetary_policy"}
    assert stock_sales_money_context(raw) == (3000000, 3000)
    del original["source"]["monetary_policy"]
    with pytest.raises(FinancePostingError, match="Retained prices"):
        stock_sales_money_context(original)


@pytest.mark.parametrize("retained,read_cap,write_cap,allowed", [
    (True, None, "20", True), (False, None, "20", True),
    (True, "20", "20", False), (False, "20", "20", False),
    (True, None, "2", False), (False, None, "2", False),
])
def test_birth_and_retained_actor_use_read_sensitivity_and_original_write_amount(
    monkeypatch: pytest.MonkeyPatch, retained: bool, read_cap: str | None, write_cap: str, allowed: bool,
) -> None:
    original = row()
    if not retained:
        original = {key: value for key, value in original["source"].items() if key != "monetary_policy"}
    before = canonical_json(original)
    commands: list[str] = []
    owner = repository(SimpleNamespace(execute=lambda query, params: commands.append(query)))
    monkeypatch.setattr(owner, "_authority_locks", lambda *args: None)
    permissions = frozenset(OPERATION_PERMISSIONS["create"])
    actor = PostingActor("maker", "maker", permissions, step_up_active=True)
    principal = ServerPrincipal(user=LocalUser(id="maker", username="maker", display_name="Maker"),
                                permissions=permissions, step_up_active=True)
    observed: dict[str, Decimal] = {}

    def authorize(permission: str, amount: int | None, precision: int = 3) -> None:
        if amount is None:
            return  # The existing generic scope gate is separate from monetary contexts.
        monetary = Decimal(exact_minor_text(amount, precision))
        observed[permission] = monetary
        maximum = read_cap if permission in READ else write_cap
        verdict = evaluate_principal_access(principal, required_permission=permission, amount=monetary,
            tenant_id="tenant", workspace_id="work", organization_id="org", entity_id="entity",
            authorized_tenant_ids=frozenset({"tenant"}), authorized_workspace_ids=frozenset({"work"}),
            authorized_organization_ids=frozenset({"org"}), authorized_entity_ids=frozenset({"entity"}),
            maximum_amount=Decimal(maximum) if maximum is not None else None)
        if not verdict.allowed:
            raise FinancePostingError("sales_scope_denied", "Current amount authority denied.")

    monkeypatch.setattr(owner.authority, "_actor", lambda actor, permission, **context: authorize(permission, context["amount"]))
    monkeypatch.setattr(owner.ops, "_actor", lambda actor, permission, scope, **context:
                        authorize(permission, scope["amount_minor"], scope["currency_precision"]))
    if allowed:
        owner._actor(actor, "create", original)
        assert {observed[permission] for permission in READ} == {Decimal("3000.000")}
        assert observed["sales.manage"] == Decimal("3.000") and len(commands) == 1
    else:
        with pytest.raises(FinancePostingError, match="amount authority denied"):
            owner._actor(actor, "create", original)
        assert commands == []
    assert canonical_json(original) == before


class _Cursor:
    description = [SimpleNamespace(name="permission_name")]

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _Connection:
    def __init__(self, *, history: set[str], active: set[tuple[str, str]], permissions: frozenset[str] = READ) -> None:
        self.history, self.active, self.permissions = history, active, permissions
        self.grant_reads = 0

    def execute(self, query: str, params: Any) -> _Cursor:
        if "DISTINCT scope_type" in query:
            return _Cursor([{"scope_type": kind} for kind in self.history])
        if "principal_scope_grants" in query:
            self.grant_reads += 1
            return _Cursor([{"scope_type": kind, "scope_id": identifier} for kind, identifier in self.active])
        if "identity_user_roles" in query:
            return _Cursor([{"permission_name": permission} for permission in self.permissions])
        return _Cursor([{"id": "reader"}])


def principal() -> ServerPrincipal:
    return ServerPrincipal(user=LocalUser(id="reader", username="reader", display_name="Reader"), permissions=READ,
        authorized_workspace_ids=frozenset({"work"}), authorized_organization_ids=frozenset({"org"}),
        authorized_legal_entity_ids=frozenset({"entity"}))


def test_cached_scope_cannot_hide_withdrawn_historical_parent_and_never_scoped_legacy_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _Connection(history={"workspace", "organization", "legal_entity"},
                             active={("workspace", "work"), ("organization", "org")})
    owner = repository(connection)
    monkeypatch.setattr(owner.authority, "_actor", lambda *args, **kwargs: None)
    with server_principal_context(principal()), pytest.raises(FinancePostingError, match="parent scope authority"):
        owner._authority_locks(PostingActor("reader", "reader", READ), "read")
    legacy = _Connection(history=set(), active=set())
    owner = repository(legacy)
    monkeypatch.setattr(owner.authority, "_actor", lambda *args, **kwargs: None)
    with server_principal_context(principal()):
        owner._authority_locks(PostingActor("reader", "reader", READ), "read")
    assert legacy.grant_reads == 0


def test_current_permission_mapping_retirement_refuses_cached_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _Connection(history=set(), active=set(), permissions=READ - {"finance_core.read"})
    owner = repository(connection)
    monkeypatch.setattr(owner.authority, "_actor", lambda *args, **kwargs: None)
    with server_principal_context(principal()), pytest.raises(FinancePostingError, match="persisted permissions"):
        owner._authority_locks(PostingActor("reader", "reader", READ), "read")


@pytest.mark.parametrize("permissions", [frozenset(), READ - {"sales.read"}, READ | {"unknown.manage"}])
def test_private_owner_union_cannot_drop_required_permissions_or_admit_unregistered_ones(permissions: frozenset[str]) -> None:
    calls: list[str] = []
    owner = repository(SimpleNamespace(execute=lambda *args: calls.append("native-query")))
    with pytest.raises(FinancePostingError, match="finite owner permission union"):
        owner._authority_locks(PostingActor("reader", "reader", READ), "read", permissions=permissions)
    assert calls == []


@pytest.mark.parametrize("boundary", ["actor-permission", "actor-step-up", "principal-step-up", "captured-scope"])
def test_create_preflight_denies_before_any_command_source_or_quantity_wait(boundary: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import reconforge.infrastructure.postgres_stock_sales as module

    calls: list[str] = []
    connection = SimpleNamespace(transaction=nullcontext, execute=lambda *args: calls.append("native-query"))
    owner = repository(connection)
    permissions = frozenset(OPERATION_PERMISSIONS["create"])
    actor = PostingActor("maker", "maker", permissions - {"sales.manage"} if boundary == "actor-permission" else permissions,
                         step_up_active=boundary != "actor-step-up")
    current = ServerPrincipal(user=LocalUser(id="maker", username="maker", display_name="Maker"), permissions=permissions,
                              step_up_active=boundary != "principal-step-up")
    monkeypatch.setattr(module, "ensure_repository_tenant_scope", lambda *args: None)
    monkeypatch.setattr(owner, "_replay", lambda *args: calls.append("command-lookup"))
    monkeypatch.setattr(owner, "_order", lambda *args, **kwargs: calls.append("source-lookup"))

    def existing_scope_preflight(*args: Any, **kwargs: Any) -> None:
        assert "amount" not in kwargs and "currency" not in kwargs
        calls.append("existing-captured-scope")
        raise FinancePostingError("sales_scope_denied", "Existing captured scope denies before source.")

    monkeypatch.setattr(owner.authority, "_actor", existing_scope_preflight)
    order = StockOrder("ORIGINAL", "CUSTOMER", "PO", "ITEM", "MAIN", "STOCK", "0.001", 3000000, "KWD",
                       "2026-10-09", "Original fractional price")
    with server_principal_context(current), pytest.raises(FinancePostingError):
        owner.create(order, command_id="retained-command", actor=actor)
    assert calls == (["existing-captured-scope"] if boundary == "captured-scope" else [])


def test_historical_create_replay_never_interprets_original_unit_through_live_currency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import reconforge.infrastructure.postgres_stock_sales as module

    owner = repository(SimpleNamespace(transaction=nullcontext, execute=lambda *args: None))
    calls: list[str] = []
    original = row()
    retained = {"unit_price_minor": "3000000", "net_unit_price_minor": "3000000", "monetary_policy": original["source"]["monetary_policy"]}
    monkeypatch.setattr(module, "ensure_repository_tenant_scope", lambda *args: None)
    monkeypatch.setattr(owner, "_authority_locks", lambda *args: calls.append("authority-before-command"))
    monkeypatch.setattr(owner, "_replay", lambda *args: calls.append("immutable-command-lookup") or retained)
    monkeypatch.setattr(owner, "_order", lambda *args, **kwargs: original)
    owner.authority._actor = lambda *args, **kwargs: calls.append("existing-scope-gate")

    def captured_policy(person: PostingActor, permission: str, scope: dict[str, Any], **kwargs: Any) -> None:
        amount = Decimal(exact_minor_text(scope["amount_minor"], scope["currency_precision"]))
        if permission in READ:
            assert amount == Decimal("3000.000") and amount <= Decimal("4000")
        else:
            assert amount == Decimal("3.000")
        calls.append("captured-policy")

    monkeypatch.setattr(owner.ops, "_actor", captured_policy)
    # The original request has no policy. Passing it to the live currency gate
    # would interpret unit3000000 as30000 at a damaged/restored live precision2.
    order = StockOrder("ORIGINAL", "CUSTOMER", "ORIGINAL", "ITEM", "MAIN", "STOCK", "0.001", 3000000, "KWD",
                       "2026-10-09", "Original fractional price")
    actor = PostingActor("maker", "maker", frozenset(OPERATION_PERMISSIONS["create"]), step_up_active=True)
    assert owner.create(order, command_id="original-create", actor=actor) is retained
    assert calls[:3] == ["authority-before-command", "immutable-command-lookup", "authority-before-command"]
    assert calls.count("captured-policy") == len(OPERATION_PERMISSIONS["create"])


def commercial_rows(count: int = 2) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    order = CommercialOrder("PARENT", "CUSTOMER", "PO", "KWD", "2026-10-09", tuple(
        CommercialLine(f"ITEM-{index}", "MAIN", "STOCK", "0.001", 3000000, "Original line") for index in range(count)))
    payload = order.payload()
    sources = [{**source, "quantity_scaled": 1, "monetary_policy": deepcopy(row()["source"]["monetary_policy"])}
               for source in payload["lines"]]
    parent = {"tenant_id": "tenant", "id": "parent", "line_count": count, "source": payload["header"],
              "currency_code": "KWD", "total_minor": payload["header"]["total_minor"],
              "source_digest": digest_payload({"header": payload["header"], "lines": sources})}
    lines = [{"tenant_id": "tenant", "order_id": "parent", "line_number": index, "total_minor": source["total_minor"],
              "source": source} for index, source in enumerate(sources, 1)]
    return parent, lines


def test_sealed_two_line_parent_reads_all_original_prices_without_rewriting_header_or_lines() -> None:
    parent, lines = commercial_rows()
    before = canonical_json([parent, lines])
    context = stock_commerce_read_context(parent, lines)
    assert stock_sales_money_context(context) == (3000000, 6000)
    assert context["source"]["monetary_policy"] == row()["source"]["monetary_policy"]
    assert canonical_json([parent, lines]) == before


def test_parent_read_does_not_expose_or_raise_amount_for_private_child_fifo_cost() -> None:
    parent, lines = commercial_rows()
    lines[0]["issue_plan"] = {"total_cost_minor": 9000000000000000000}
    context = stock_commerce_read_context(parent, lines)
    assert stock_sales_money_context(context) == (3000000, 6000)


@pytest.mark.parametrize("mutation", ["missing", "extra", "order", "tenant", "parent", "header", "seal", "total", "policy", "bool"])
def test_parent_projection_refuses_incomplete_foreign_or_unsealed_original_population(mutation: str) -> None:
    parent, lines = commercial_rows()
    if mutation == "missing":
        lines.pop()
    elif mutation == "extra":
        lines.append(deepcopy(lines[0]))
    elif mutation == "order":
        lines.reverse()
    elif mutation in {"tenant", "parent"}:
        lines[0]["tenant_id" if mutation == "tenant" else "order_id"] = "foreign"
    elif mutation == "header":
        parent["source"]["schema_version"] = "other"
    elif mutation == "seal":
        parent["source_digest"] = "b" * 64
    elif mutation == "total":
        parent["total_minor"] += 1
    elif mutation == "policy":
        lines[1]["source"]["monetary_policy"]["registry_version"] = "different"
    else:
        lines[0]["source"]["monetary_policy"]["precision"] = True
    with pytest.raises(FinancePostingError):
        stock_commerce_read_context(parent, lines)


def test_commercial_original_population_bound_admits_1000_and_refuses_1001() -> None:
    parent, lines = commercial_rows(1000)
    assert stock_sales_money_context(stock_commerce_read_context(parent, lines)) == (3000000, 3000000)
    lines.append(deepcopy(lines[-1]))
    with pytest.raises(FinancePostingError, match="complete sealed lines"):
        stock_commerce_read_context(parent, lines)


def test_commercial_get_pins_authority_before_source_and_rechecks_after_native_closure(monkeypatch: pytest.MonkeyPatch) -> None:
    import reconforge.infrastructure.postgres_stock_commerce as module

    parent, lines = commercial_rows()
    calls: list[str] = []
    view = {"source_digest": parent["source_digest"], "lines": lines}

    def execute(query: str, args: Any) -> Any:
        if "stock_commerce_lines l JOIN" in query:
            return SimpleNamespace(fetchall=lambda: lines)
        calls.append("native-closure")
        return None

    owner = PostgresStockCommerceRepository(SimpleNamespace(transaction=nullcontext, execute=execute), "tenant", **SCOPE)
    monkeypatch.setattr(module, "ensure_repository_tenant_scope", lambda *args: None)
    monkeypatch.setattr(owner.native, "_authority_locks", lambda *args: calls.append("current-authority"))

    def locked_source(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert kwargs == {"read_lock": True}
        calls.append("source-share")
        return parent

    monkeypatch.setattr(owner, "_row", locked_source)
    monkeypatch.setattr(owner, "_snapshot", lambda *args: view)

    def authorize(person: PostingActor, operation: str, projection: dict[str, Any]) -> None:
        assert operation == "read" and stock_sales_money_context(projection) == (3000000, 6000)
        calls.append("captured-read")

    monkeypatch.setattr(owner.native, "_actor", authorize)
    assert owner.get("parent", actor=PostingActor("reader", "reader", READ)) is view
    assert calls == ["current-authority", "source-share", "captured-read", "native-closure", "captured-read"]


@pytest.mark.parametrize("operation", ["create", "open-tranche", "approve-tranche", "prepare-issue", "collect"])
def test_commercial_authority_pins_fixed_union_before_parent_wait_and_preserves_aggregate(operation: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    owner = PostgresStockCommerceRepository(SimpleNamespace(execute=lambda *args: calls.append("owner-context")), "tenant", **SCOPE)
    parent, _ = commercial_rows()
    permissions = COMMERCE_PERMISSIONS[operation]
    actor = PostingActor("maker", "maker", permissions, step_up_active=True)

    def pin(person: PostingActor, phase: str, *, permissions: frozenset[str]) -> None:
        assert person is actor and phase == operation and permissions is COMMERCE_PERMISSIONS[operation]
        calls.append("union-before-parent")

    def unchanged_amount(person: PostingActor, permission: str, **context: Any) -> None:
        assert context == {"mutation": True, "amount": 6000, "currency": "KWD"}
        calls.append("original-parent-aggregate")

    monkeypatch.setattr(owner.native, "_authority_locks", pin)
    monkeypatch.setattr(owner.native.authority, "_actor", unchanged_amount)
    owner._authority(actor, operation, parent)
    assert calls == ["union-before-parent", *(["original-parent-aggregate"] * len(permissions)), "owner-context", "owner-context"]
