"""Deterministic permission-to-route inventory derived from API dependencies."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass

from fastapi import APIRouter
from fastapi.routing import APIRoute


@dataclass(frozen=True, order=True)
class RouteAuthorizationContract:
    """One normalized API authorization boundary."""

    method: str
    path: str
    mode: str
    permissions: tuple[str, ...] = ()


_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_PUBLIC_MUTATION_ALLOWLIST = frozenset(
    {
        ("POST", "/api/v1/auth/login"),
        ("POST", "/api/v1/auth/browser/login"),
        ("POST", "/api/v1/auth/federation/challenge"),
        ("POST", "/api/v1/auth/federated-login"),
    }
)
_IDENTITY_MUTATION_ALLOWLIST = frozenset(
    {
        ("POST", "/api/v1/auth/logout"),
        ("POST", "/api/v1/auth/step-up"),
        ("POST", "/api/v1/auth/emergency-access/requests/{access_id}/activate"),
        ("POST", "/api/v1/auth/emergency-access/requests/{access_id}/end"),
        ("POST", "/api/v1/auth/webauthn/registration/options"),
        ("POST", "/api/v1/auth/webauthn/registration/verify"),
        ("POST", "/api/v1/auth/webauthn/authentication/options"),
        ("POST", "/api/v1/auth/webauthn/authentication/verify"),
    }
)

# These are the financial-control mutations whose permission must not drift to
# a broader or merely adjacent capability while still looking "protected".
# The route inventory validates this contract at application construction time.
_CRITICAL_ROUTE_CONTRACTS: dict[tuple[str, str], tuple[str, tuple[str, ...]]] = {
    ("POST", "/api/v1/ops/durable-jobs/{job_id}/cancel"): ("all", ("jobs.manage",)),
    ("POST", "/api/v1/ops/durable-jobs/{job_id}/requeue"): ("all", ("jobs.manage",)),
    ("POST", "/api/v1/inventory-receipt-posting/plans"): (
        "all", ("finance_core.manage", "finance_core.read", "inventory.manage", "inventory.read", "inventory.valuation.manage")
    ),
    ("POST", "/api/v1/inventory-receipt-posting/plans/{plan_id}/review"): (
        "all", ("finance_core.read", "finance_core.validate", "inventory.post", "inventory.read", "inventory.valuation.approve")
    ),
    ("POST", "/api/v1/inventory-receipt-posting/plans/{plan_id}/commit"): (
        "all", ("finance_core.post", "finance_core.read", "inventory.post", "inventory.read", "inventory.valuation.approve")
    ),
    ("POST", "/api/v1/inventory-receipt-posting/plans/{plan_id}/reversal"): (
        "all", ("finance_core.manage", "finance_core.read", "finance_core.reverse", "inventory.manage", "inventory.read",
                "inventory.valuation.manage", "inventory.valuation.reverse.manage")
    ),
    ("POST", "/api/v1/accounts/reconciliations"): ("all", ("accounts.prepare",)),
    ("POST", "/api/v1/accounts/reconciliations/{reconciliation_id}/prepare"): ("all", ("accounts.prepare",)),
    ("POST", "/api/v1/accounts/reconciliations/{reconciliation_id}/submit"): ("all", ("accounts.prepare",)),
    ("POST", "/api/v1/accounts/reconciliations/{reconciliation_id}/review"): ("all", ("accounts.review",)),
    ("POST", "/api/v1/accounts/reconciliations/{reconciliation_id}/complete"): ("all", ("accounts.complete",)),
    ("POST", "/api/v1/close/periods"): ("all", ("close.manage",)),
    ("POST", "/api/v1/close/periods/{period_id}/lock"): ("all", ("close.manage",)),
    ("POST", "/api/v1/close/periods/{period_id}/reopen"): ("all", ("close.manage",)),
    ("POST", "/api/v1/close/tasks/{task_id}/status"): ("all", ("close.manage",)),
    ("POST", "/api/v1/reconciliations/runs"): ("any", ("match.run", "reconciliation.manage")),
    ("POST", "/api/v1/reconciliations/runs/{run_id}/cancel"): ("any", ("match.run", "reconciliation.manage")),
    ("POST", "/api/v1/reconciliations/runs/{run_id}/requeue"): ("any", ("match.run", "reconciliation.manage")),
    ("POST", "/api/v1/connectors/writeback/intents"): ("all", ("connectors.writeback.propose",)),
    ("POST", "/api/v1/connectors/writeback/intents/{intent_id}/approve"): (
        "all",
        ("connectors.writeback.approve",),
    ),
    ("POST", "/api/v1/connectors/writeback/intents/{intent_id}/dispatch"): (
        "all",
        ("connectors.writeback.dispatch",),
    ),
    ("POST", "/api/v1/connectors/writeback/intents/{intent_id}/compensate"): (
        "all",
        ("connectors.writeback.compensate",),
    ),
    ("POST", "/api/v1/connectors/writeback/intents/{intent_id}/compensate/dispatch"): (
        "all",
        ("connectors.writeback.dispatch",),
    ),
    ("POST", "/api/v1/connectors/writeback/intents/{intent_id}/acknowledge"): (
        "all",
        ("connectors.writeback.reconcile",),
    ),
    ("POST", "/api/v1/connectors/writeback/intents/{intent_id}/recover"): (
        "all",
        ("connectors.writeback.reconcile",),
    ),
    ("POST", "/api/v1/finance-core/entries/{entry_id}/validate"): ("all", ("finance_core.validate",)),
    ("POST", "/api/v1/finance-core/entries/{entry_id}/void"): ("all", ("finance_core.validate",)),
    ("POST", "/api/v1/finance-core/entries/{entry_id}/post"): ("all", ("finance_core.post",)),
    ("POST", "/api/v1/budget-control/envelopes"): ("all", ("budget_control.manage",)),
    ("POST", "/api/v1/budget-control/envelopes/{budget_id}/submit"): (
        "all",
        ("budget_control.manage",),
    ),
    ("POST", "/api/v1/budget-control/envelopes/{budget_id}/approve"): (
        "all",
        ("budget_control.approve",),
    ),
    ("POST", "/api/v1/budget-control/envelopes/{budget_id}/commitments"): (
        "all",
        ("budget_control.manage",),
    ),
    ("POST", "/api/v1/budget-control/envelopes/{budget_id}/commitments/{commitment_id}/events"): (
        "all",
        ("budget_control.manage",),
    ),
    ("GET", "/api/v1/exceptions"): ("any", ("exceptions.manage", "exceptions.read")),
    ("GET", "/api/v1/exceptions/{exception_id}"): ("any", ("exceptions.manage", "exceptions.read")),
    ("POST", "/api/v1/exceptions/{exception_id}/assign"): ("all", ("exceptions.manage",)),
    ("POST", "/api/v1/exceptions/{exception_id}/status"): ("all", ("exceptions.manage",)),
    ("GET", "/api/v1/finance-core/posted-balances-as-of"): (
        "any", ("finance_core.manage", "finance_core.post", "finance_core.read", "finance_core.validate"),
    ),
    ("POST", "/api/v1/finance-core/postings/{effect_id}/reversal"): (
        "all", ("finance_core.manage", "finance_core.reverse"),
    ),
    ("POST", "/api/v1/inventory/movements/{movement_id}/post"): ("all", ("inventory.post",)),
    ("POST", "/api/v1/inventory/movements/{movement_id}/void"): ("all", ("inventory.post",)),
    ("POST", "/api/v1/consolidation-close/periods/{period_id}/lock"): ("all", ("finance_core.validate",)),
    ("POST", "/api/v1/consolidation-close/periods/{period_id}/reopen"): ("all", ("finance_core.validate",)),
    ("POST", "/api/v1/consolidation-close/runs/{run_id}/approve"): ("all", ("finance_core.validate",)),
    ("POST", "/api/v1/consolidation-close/runs/{run_id}/post"): ("all", ("finance_core.validate",)),
    ("POST", "/api/v1/consolidation-close/runs/{run_id}/reversal/approve"): (
        "all",
        ("finance_core.validate",),
    ),
    ("POST", "/api/v1/consolidation-close/runs/{run_id}/reversal/request"): (
        "all",
        ("finance_core.manage",),
    ),
    ("POST", "/api/v1/evidence/records/{evidence_id}/verify"): ("all", ("evidence.verify",)),
    ("POST", "/api/v1/notifications/inbox"): ("all", ("notifications.publish",)),
    ("POST", "/api/v1/notifications/inbox/{notification_id}/read"): ("all", ("notifications.read",)),
    ("POST", "/api/v1/auth/emergency-access/requests"): ("all", ("security.emergency.request",)),
    ("POST", "/api/v1/auth/emergency-access/requests/{access_id}/approve"): (
        "all",
        ("security.emergency.approve",),
    ),
    ("POST", "/api/v1/auth/emergency-access/requests/{access_id}/reject"): (
        "all",
        ("security.emergency.approve",),
    ),
    ("POST", "/api/v1/auth/emergency-access/requests/{access_id}/review"): (
        "all",
        ("security.emergency.review",),
    ),
}


_SALES_READ = frozenset({"sales.read", "receivables.read", "finance_core.read"})
_PROCUREMENT_READ = frozenset({"payables.read", "inventory.read", "finance_core.read"})


def _erp_contract(base: frozenset[str], *permissions: str) -> tuple[str, tuple[str, ...]]:
    return "all", tuple(sorted(base | frozenset(permissions)))


_CRITICAL_ROUTE_CONTRACTS.update({
    ("POST", "/api/v1/operational-finance/plans"): ("all", ("finance_core.manage",)),
    ("POST", "/api/v1/operational-finance/plans/{plan_id}/review"): ("all", ("finance_core.validate",)),
    ("POST", "/api/v1/operational-finance/plans/{plan_id}/post"): ("all", ("finance_core.post",)),
    ("POST", "/api/v1/sales-revenue/quotations"): _erp_contract(_SALES_READ, "sales.manage"),
    ("POST", "/api/v1/sales-revenue/documents/{identifier}/submit"): _erp_contract(_SALES_READ, "sales.manage"),
    ("POST", "/api/v1/sales-revenue/documents/{identifier}/approve"): _erp_contract(_SALES_READ, "sales.approve"),
    ("POST", "/api/v1/sales-revenue/documents/{identifier}/order"): _erp_contract(_SALES_READ, "sales.manage"),
    ("POST", "/api/v1/sales-revenue/documents/{identifier}/fulfill"): _erp_contract(_SALES_READ, "sales.manage"),
    ("POST", "/api/v1/sales-revenue/documents/{identifier}/cancel"): _erp_contract(_SALES_READ, "sales.manage"),
    ("POST", "/api/v1/sales-revenue/documents/{identifier}/invoice/prepare"): _erp_contract(_SALES_READ, "sales.manage", "receivables.manage", "finance_core.manage"),
    ("POST", "/api/v1/sales-revenue/documents/{identifier}/invoice/review"): _erp_contract(_SALES_READ, "sales.approve", "receivables.approve", "finance_core.validate"),
    ("POST", "/api/v1/sales-revenue/documents/{identifier}/invoice/post"): _erp_contract(_SALES_READ, "sales.manage", "receivables.approve", "finance_core.post"),
    ("POST", "/api/v1/sales-revenue/documents/{identifier}/collection/prepare"): _erp_contract(_SALES_READ, "sales.manage", "finance_core.manage"),
    ("POST", "/api/v1/sales-revenue/documents/{identifier}/collection/review"): _erp_contract(_SALES_READ, "sales.approve", "finance_core.validate"),
    ("POST", "/api/v1/sales-revenue/documents/{identifier}/collection/post"): _erp_contract(_SALES_READ, "sales.manage", "receivables.manage", "finance_core.post"),
    ("POST", "/api/v1/procurement-operations/cycles"): _erp_contract(_PROCUREMENT_READ, "payables.manage"),
})
for _operation, _permissions in {
    "submit-order": ("payables.manage",),
    "approve-order": ("payables.approve",),
    "prepare-receipt": ("payables.manage", "inventory.manage", "inventory.valuation.manage", "finance_core.manage"),
    "review-receipt": ("payables.approve", "inventory.post", "inventory.valuation.approve", "finance_core.validate"),
    "receive": ("payables.manage", "inventory.post", "inventory.valuation.approve", "finance_core.post"),
    "match-invoice": ("payables.manage", "payables.match"),
    "approve-invoice": ("payables.approve",),
    "prepare-accrual": ("payables.manage", "finance_core.manage"),
    "review-accrual": ("payables.approve", "finance_core.validate"),
    "post-accrual": ("payables.approve", "finance_core.post"),
    "prepare-payment": ("payables.settle", "finance_core.manage"),
    "review-payment": ("payables.settle", "finance_core.validate"),
    "pay": ("payables.settle", "finance_core.post"),
}.items():
    _CRITICAL_ROUTE_CONTRACTS[("POST", "/api/v1/procurement-operations/cycles/{cycle_id}/commands/" + _operation)] = _erp_contract(_PROCUREMENT_READ, *_permissions)
    if _operation not in {"prepare-payment", "review-payment", "pay"}:
        _CRITICAL_ROUTE_CONTRACTS[("POST", "/api/v1/procurement-partial/orders/{order_id}/commands/" + _operation)] = _erp_contract(_PROCUREMENT_READ, *_permissions)

_CRITICAL_ROUTE_CONTRACTS[("POST", "/api/v1/procurement-partial/orders")] = _erp_contract(_PROCUREMENT_READ, "payables.manage")
_CRITICAL_ROUTE_CONTRACTS[("POST", "/api/v1/procurement-partial/orders/multiline")] = _erp_contract(_PROCUREMENT_READ, "payables.manage")
_CRITICAL_ROUTE_CONTRACTS[("POST", "/api/v1/procurement-partial/orders/{order_id}/commands/prepare-receipt-line")] = _erp_contract(
    _PROCUREMENT_READ, "payables.manage", "inventory.manage", "inventory.valuation.manage", "finance_core.manage")
_CRITICAL_ROUTE_CONTRACTS[("POST", "/api/v1/procurement-partial/orders/{order_id}/commands/match-invoice-lines")] = _erp_contract(
    _PROCUREMENT_READ, "payables.manage", "payables.match")
_STOCK_READ = _SALES_READ | frozenset({"inventory.read"})
for _path, _permissions in {
    "": ("sales.manage",),
    "/{identifier}/submit": ("sales.manage",),
    "/{identifier}/approve": ("sales.approve",),
    "/{identifier}/reserve": ("sales.manage", "inventory.manage"),
    "/{identifier}/issue/prepare": ("sales.manage", "inventory.manage", "inventory.valuation.manage", "finance_core.manage"),
    "/{identifier}/issue/review": ("sales.approve", "inventory.valuation.approve", "finance_core.validate"),
    "/{identifier}/deliver": ("sales.manage", "inventory.post", "inventory.valuation.approve", "finance_core.post"),
    "/{identifier}/invoice/prepare": ("sales.manage", "receivables.manage", "finance_core.manage"),
    "/{identifier}/invoice/review": ("sales.approve", "receivables.approve", "finance_core.validate"),
    "/{identifier}/invoice/post": ("sales.manage", "receivables.approve", "finance_core.post"),
    "/{identifier}/collection/prepare": ("sales.manage", "finance_core.manage"),
    "/{identifier}/collection/review": ("sales.approve", "finance_core.validate"),
    "/{identifier}/collection/post": ("sales.manage", "receivables.manage", "finance_core.post"),
    "/{identifier}/cancel": ("sales.manage", "finance_core.manage"),
}.items():
    _CRITICAL_ROUTE_CONTRACTS[("POST", "/api/v1/stock-sales/orders" + _path)] = _erp_contract(_STOCK_READ, *_permissions)
_CRITICAL_ROUTE_CONTRACTS[("POST", "/api/v1/stock-sales/commerce/orders")] = _erp_contract(_STOCK_READ, "sales.manage")
for _operation, _permissions in {
    "submit": ("sales.manage",), "approve": ("sales.approve",),
    "open-tranche": ("sales.manage",), "approve-tranche": ("sales.approve", "sales.manage", "inventory.manage"),
    "prepare-issue": ("sales.manage", "inventory.manage", "inventory.valuation.manage", "finance_core.manage"),
    "review-issue": ("sales.approve", "inventory.valuation.approve", "finance_core.validate"),
    "deliver": ("sales.manage", "inventory.post", "inventory.valuation.approve", "finance_core.post"),
    "prepare-invoice": ("sales.manage", "receivables.manage", "finance_core.manage"),
    "review-invoice": ("sales.approve", "receivables.approve", "finance_core.validate"),
    "invoice": ("sales.manage", "receivables.approve", "finance_core.post"),
    "prepare-collection": ("sales.manage", "finance_core.manage"),
    "review-collection": ("sales.approve", "finance_core.validate"),
    "collect": ("sales.manage", "receivables.manage", "finance_core.post"),
    "cancel": ("sales.manage", "finance_core.manage"),
}.items():
    _CRITICAL_ROUTE_CONTRACTS[("POST", "/api/v1/stock-sales/commerce/orders/{identifier}/" + _operation)] = _erp_contract(_STOCK_READ, *_permissions)
for _path, _permission in {
    "/maps": "finance_core.manage",
    "/maps/{map_id}/review": "finance_core.validate",
    "/openings": "finance_core.manage",
    "/openings/{opening_id}/review": "finance_core.validate",
    "/openings/{opening_id}/post": "finance_core.post",
}.items():
    _CRITICAL_ROUTE_CONTRACTS[("POST", "/api/v1/financial-reporting" + _path)] = ("all", (_permission,))
for _path, _permission in {"": "finance_core.manage", "/{plan_id}/review": "finance_core.validate", "/{plan_id}/post": "finance_core.post"}.items():
    _CRITICAL_ROUTE_CONTRACTS[("POST", "/api/v1/financial-installments/plans" + _path)] = _erp_contract(frozenset({"payables.settle"}), _permission)



def _dependency_contract(route: APIRoute) -> tuple[str, tuple[str, ...]] | None:
    found: set[tuple[str, tuple[str, ...]]] = set()
    pending = list(route.dependant.dependencies)
    while pending:
        dependency = pending.pop()
        call = dependency.call
        mode = getattr(call, "__reconforge_permission_mode__", None)
        permissions = getattr(call, "__reconforge_permissions__", None)
        if isinstance(mode, str) and isinstance(permissions, frozenset):
            found.add((mode, tuple(sorted(str(value) for value in permissions))))
        pending.extend(dependency.dependencies)
    if len(found) > 1:
        raise ValueError(f"Route {route.path} has ambiguous authorization contracts.")
    return next(iter(found)) if found else None


def build_route_authorization_inventory(
    routers: Iterable[APIRouter],
    *,
    prefix: str,
    identity_routes: frozenset[tuple[str, str]],
    public_routes: frozenset[tuple[str, str]],
) -> tuple[RouteAuthorizationContract, ...]:
    """Build a closed inventory and reject every unclassified API operation."""

    contracts: list[RouteAuthorizationContract] = []
    seen: set[tuple[str, str]] = set()
    for router in routers:
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            path = prefix + route.path
            dependency_contract = _dependency_contract(route)
            for method in sorted(route.methods or set()):
                key = (method, path)
                if key in seen:
                    raise ValueError(f"Duplicate API authorization contract for {method} {path}.")
                seen.add(key)
                if dependency_contract is not None:
                    mode, permissions = dependency_contract
                elif key in identity_routes:
                    mode, permissions = "identity", ()
                elif key in public_routes:
                    mode, permissions = "public", ()
                else:
                    raise ValueError(f"API route lacks an authorization contract: {method} {path}.")
                contracts.append(RouteAuthorizationContract(method, path, mode, permissions))
    declared = identity_routes | public_routes
    if not declared <= seen:
        raise ValueError("Authorization allowlist contains a route that is not registered.")
    return tuple(sorted(contracts))


def authorization_inventory_digest(contracts: Iterable[RouteAuthorizationContract]) -> str:
    """Return a stable digest for review and release evidence."""

    payload = json.dumps(
        [asdict(contract) for contract in sorted(contracts)],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def validate_authorization_surface(
    contracts: Iterable[RouteAuthorizationContract],
    *,
    require_critical_routes: bool = False,
) -> None:
    """Fail closed when a mutating route escapes its declared policy boundary.

    Public and identity-only mutations are deliberately limited to the small
    authentication handshake allowlists. SCIM is a separate protocol boundary
    and is classified explicitly by its `scim` mode. Every other mutation must
    carry a permission-bearing or dynamic policy contract.
    """

    normalized_contracts = tuple(contracts)
    actual_by_route = {(contract.method, contract.path): contract for contract in normalized_contracts}
    missing_critical = sorted(set(_CRITICAL_ROUTE_CONTRACTS) - set(actual_by_route))
    if require_critical_routes and missing_critical:
        raise ValueError(f"Critical authorization routes are not registered: {missing_critical}.")

    for contract in normalized_contracts:
        key = (contract.method, contract.path)
        if contract.method not in _MUTATING_METHODS:
            continue
        if contract.mode == "public" and key not in _PUBLIC_MUTATION_ALLOWLIST:
            raise ValueError(f"Mutating API route is publicly authorized: {contract.method} {contract.path}.")
        if contract.mode == "identity" and key not in _IDENTITY_MUTATION_ALLOWLIST:
            raise ValueError(f"Mutating API route has identity-only authorization: {contract.method} {contract.path}.")
        if contract.mode in {"all", "any"} and not contract.permissions:
            raise ValueError(f"Mutating API route lacks a permission contract: {contract.method} {contract.path}.")
        if contract.mode not in {"all", "any", "dynamic", "identity", "public", "scim"}:
            raise ValueError(f"Mutating API route has unsupported authorization mode: {contract.method} {contract.path}.")
        expected = _CRITICAL_ROUTE_CONTRACTS.get(key)
        if expected is not None and (contract.mode, contract.permissions) != expected:
            raise ValueError(
                "Critical API route authorization contract drifted: "
                f"{contract.method} {contract.path} expected {expected}, "
                f"got {(contract.mode, contract.permissions)}."
            )
