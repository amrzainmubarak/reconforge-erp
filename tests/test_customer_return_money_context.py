"""Finite original money projection; quantities and unrelated numbers are not amounts."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import FinancePostingError, PostingActor, canonical_json
from reconforge.domain.operational_finance import exact_minor_text
from reconforge.infrastructure.postgres_customer_returns import (
    READ,
    PostgresCustomerReturnsRepository,
    customer_return_money_context,
)
from reconforge.platform.common import ServerPrincipal, server_principal_context


def original() -> dict[str, Any]:
    policy = {"currency_code": "KWD", "currency_precision": 3, "currency_rounding_policy": "ROUND_HALF_UP",
              "currency_registry_version": "synthetic-v1", "currency_registry_digest": "a" * 64}
    compact = dict(zip(("currency_code", "precision", "rounding_policy", "registry_version", "registry_digest"),
                       policy.values(), strict=True))
    snapshot = {"entry": policy, "lines": [{"debit_minor": 1, "credit_minor": 0}, {"debit_minor": 0, "credit_minor": 1}]}
    effect = {**policy, "snapshot_json": snapshot}
    return {"operation": "Return", "currency_code": "KWD", "currency_precision": 3, "amount_minor": 6001,
            "credit_minor": 3000, "refund_entitlement_minor": 3000, "receivable_released_minor": 0,
            "cogs_restored_minor": 1, "turnover_minor": 6001,
            "workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity",
            "source_snapshot": {"allocated_minor": 3000,
                "invoice": {**policy, "subtotal_minor": 3000, "tax_minor": 0, "total_minor": 3000},
                "stock": {"currency_code": "KWD", "total_minor": 3000,
                    "source": {"currency_code": "KWD", "monetary_policy": compact,
                        "unit_price_minor": 3000000, "net_unit_price_minor": 3000000, "tax_minor": 0, "total_minor": 3000,
                        "quantity": "0.001", "quantity_scaled": 1, "discount_basis_points": 0},
                    "issue_plan": {"currency_policy": compact, "total_cost_minor": 1,
                        "allocations": [{"remaining_value_minor": 1000, "value_minor": 1, "quantity_scaled": 1}]}},
                "cogs": effect, "revenue": deepcopy(effect), "consumptions": [{"value_minor": 1, "quantity_scaled": 1}]},
            "entries": [{"snapshot": deepcopy(snapshot)}]}


def set_path(value: Any, path: tuple[Any, ...], replacement: Any) -> None:
    for part in path[:-1]:
        value = value[part]
    value[path[-1]] = replacement


MONEY_PATHS = [
    (key,) for key in ("amount_minor", "credit_minor", "refund_entitlement_minor", "receivable_released_minor",
                       "cogs_restored_minor", "turnover_minor")
] + [
    ("source_snapshot", "allocated_minor"),
    *( ("source_snapshot", "invoice", key) for key in ("subtotal_minor", "tax_minor", "total_minor") ),
    ("source_snapshot", "stock", "total_minor"),
    *( ("source_snapshot", "stock", "source", key) for key in ("unit_price_minor", "net_unit_price_minor", "tax_minor", "total_minor") ),
    ("source_snapshot", "stock", "issue_plan", "total_cost_minor"),
    ("source_snapshot", "stock", "issue_plan", "allocations", 0, "remaining_value_minor"),
    ("source_snapshot", "stock", "issue_plan", "allocations", 0, "value_minor"),
    ("source_snapshot", "consumptions", 0, "value_minor"),
    *( ("source_snapshot", effect, "snapshot_json", "lines", 0, key) for effect in ("cogs", "revenue")
       for key in ("debit_minor", "credit_minor") ),
    *( ("entries", 0, "snapshot", "lines", 0, key) for key in ("debit_minor", "credit_minor") ),
]


def test_fractional_original_unit_price_sets_amount_and_preserves_all_original_bytes() -> None:
    plan = original()
    before = canonical_json(plan)
    scope = customer_return_money_context(plan)
    assert Decimal(exact_minor_text(scope["amount_minor"], scope["currency_precision"])) == Decimal("3000.000")
    assert plan["amount_minor"] == 6001 and plan["source_snapshot"]["stock"]["total_minor"] == 3000
    assert canonical_json(plan) == before
    assert scope["source_snapshot"] == plan["source_snapshot"] and scope["entries"] == plan["entries"]


@pytest.mark.parametrize("path", MONEY_PATHS)
def test_each_retained_money_path_independently_covers_a_larger_exposure(path: tuple[Any, ...]) -> None:
    plan = original()
    set_path(plan, path, 4000001)
    assert customer_return_money_context(plan)["amount_minor"] == 4000001


@pytest.mark.parametrize("value", [True, False, 1.5, "3000000", None, -1, 9000000000000000001])
def test_original_price_never_coerces_malformed_money(value: object) -> None:
    plan = original()
    plan["source_snapshot"]["stock"]["source"]["unit_price_minor"] = value
    with pytest.raises(FinancePostingError, match="Retained monetary"):
        customer_return_money_context(plan)


@pytest.mark.parametrize("path", [
    ("currency_precision",), ("source_snapshot", "stock", "source", "monetary_policy", "precision"),
    ("source_snapshot", "stock", "issue_plan", "currency_policy", "precision"),
    ("source_snapshot", "cogs", "currency_precision"),
    ("source_snapshot", "revenue", "snapshot_json", "entry", "currency_precision"),
    ("entries", 0, "snapshot", "entry", "currency_precision"),
])
def test_every_exposed_native_snapshot_requires_the_exact_original_precision(path: tuple[Any, ...]) -> None:
    plan = original()
    set_path(plan, path, 2)
    with pytest.raises(FinancePostingError, match="Retained monetary"):
        customer_return_money_context(plan)


def test_currency_registry_affinity_and_bool_precision_refuse_instead_of_reinterpreting() -> None:
    for path, value in (
        (("source_snapshot", "invoice", "currency_precision"), True),
        (("source_snapshot", "stock", "source", "monetary_policy", "currency_code"), "USD"),
        (("source_snapshot", "stock", "issue_plan", "currency_policy", "registry_digest"), "b" * 64),
    ):
        plan = original()
        set_path(plan, path, value)
        with pytest.raises(FinancePostingError, match="Retained monetary"):
            customer_return_money_context(plan)


def test_quantities_versions_and_unknown_numeric_metadata_do_not_become_money() -> None:
    plan = original()
    plan.update(row_version=9000000000000000000, unrelated_number=9000000000000000000)
    quote = plan["source_snapshot"]["stock"]["source"]
    quote.update(quantity_scaled=9000000000000000000, discount_basis_points=9999)
    assert customer_return_money_context(plan)["amount_minor"] == 3000000


def test_refund_installment_and_every_outer_permission_still_cover_original_source(monkeypatch: pytest.MonkeyPatch) -> None:
    parent = original()
    child = {key: parent[key] for key in ("currency_code", "currency_precision", "workspace_id", "organization_id", "legal_entity_id")}
    child.update(operation="Refund", return_id="original", amount_minor=1, refunded_before_minor=3000)
    before = canonical_json([parent, child])
    repository = PostgresCustomerReturnsRepository(None, "tenant")
    monkeypatch.setattr(repository, "_authority_locks", lambda *args: None)
    monkeypatch.setattr(repository, "_row", lambda identifier: parent)
    observed: list[tuple[str, int, int]] = []

    def authorize(actor: PostingActor, permission: str, scope: dict[str, Any], **kwargs: Any) -> None:
        observed.append((permission, scope["amount_minor"], scope["currency_precision"]))

    monkeypatch.setattr(repository.owner, "_actor", authorize)
    repository._actor(PostingActor("reader", "reader", READ), "read", child)
    assert len(observed) == 8 and {permission for permission, _, _ in observed} == READ
    assert all((amount, precision) == (3000000, 3) for _, amount, precision in observed)
    assert canonical_json([parent, child]) == before
    child["refunded_before_minor"] = 4000000
    assert customer_return_money_context(child, parent=parent)["amount_minor"] == 4000000


def test_scope_only_list_retains_none_and_saved_return_missing_original_refuses() -> None:
    scope = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
    assert customer_return_money_context(scope) == scope and "amount_minor" not in customer_return_money_context(scope)
    with pytest.raises(FinancePostingError, match="Original monetary source is missing"):
        customer_return_money_context({**scope, "operation": "Return"})


@pytest.mark.parametrize("path", [
    ("source_snapshot", "consumptions"), ("source_snapshot", "stock", "issue_plan", "allocations"),
    ("source_snapshot", "cogs", "snapshot_json", "lines"), ("entries",),
])
def test_empty_original_populations_refuse_without_silent_zero(path: tuple[Any, ...]) -> None:
    plan = original()
    set_path(plan, path, [])
    with pytest.raises(FinancePostingError, match="Retained monetary"):
        customer_return_money_context(plan)


class _AuthorityCursor:
    description = [SimpleNamespace(name="permission_name")]

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _AuthorityConnection:
    def __init__(self, grants: set[tuple[str, str]], permissions: frozenset[str] = READ) -> None:
        self.grants, self.permissions = grants, permissions
        self.kinds_requested: list[str] | None = None

    def execute(self, query: str, params: tuple[Any, ...]) -> _AuthorityCursor:
        if "principal_scope_grants" in query:
            self.kinds_requested = params[2]
            return _AuthorityCursor([{"scope_type": kind, "scope_id": identifier} for kind, identifier in self.grants
                                     if kind in params[2]])
        if "identity_user_roles" in query:
            return _AuthorityCursor([{"permission_name": permission} for permission in self.permissions])
        return _AuthorityCursor([{"id": "reader"}])


@pytest.mark.parametrize("bounded", [False, True])
def test_legacy_all_empty_scope_and_workspace_bound_inheritance_keep_existing_meaning(bounded: bool) -> None:
    connection = _AuthorityConnection({("workspace", "work")} if bounded else set())
    principal = ServerPrincipal(user=LocalUser(id="reader", username="reader", display_name="Reader"), permissions=READ,
        authorized_workspace_ids=frozenset({"work"}) if bounded else frozenset())
    owner = PostgresCustomerReturnsRepository(connection, "tenant")
    with server_principal_context(principal):
        owner._authority_locks(PostingActor("reader", "reader", READ), "read", original())
    assert connection.kinds_requested == (["workspace"] if bounded else None)


def test_bound_original_scope_cannot_fall_back_to_cached_parent_after_one_grant_withdrawal() -> None:
    connection = _AuthorityConnection({("workspace", "work"), ("organization", "org")})
    principal = ServerPrincipal(user=LocalUser(id="reader", username="reader", display_name="Reader"), permissions=READ,
        authorized_workspace_ids=frozenset({"work"}), authorized_organization_ids=frozenset({"org"}),
        authorized_legal_entity_ids=frozenset({"entity"}))
    with server_principal_context(principal), pytest.raises(FinancePostingError, match="scope authority"):
        PostgresCustomerReturnsRepository(connection, "tenant")._authority_locks(PostingActor("reader", "reader", READ), "read", original())


def test_current_permission_retirement_refuses_even_when_bound_principal_still_contains_it() -> None:
    connection = _AuthorityConnection(set(), READ - {"finance_core.read"})
    principal = ServerPrincipal(user=LocalUser(id="reader", username="reader", display_name="Reader"), permissions=READ)
    with server_principal_context(principal), pytest.raises(FinancePostingError, match="Current authorization"):
        PostgresCustomerReturnsRepository(connection, "tenant")._authority_locks(PostingActor("reader", "reader", READ), "read", original())
