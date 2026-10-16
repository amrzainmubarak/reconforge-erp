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
for _path in ("/plans", "/plans/{plan_id}", "/sources/{source_order_id}/balance"):
    _CRITICAL_ROUTE_CONTRACTS[("GET", "/api/v1/customer-partial-returns" + _path)] = _erp_contract(_STOCK_READ)
for _path, _permissions in {
    "": ("sales.manage", "receivables.manage", "inventory.valuation.manage", "finance_core.manage", "finance_core.reverse"),
    "/{return_id}/refunds": ("sales.manage", "receivables.manage", "inventory.valuation.manage", "finance_core.manage", "finance_core.reverse"),
    "/{original_id}/reversals": ("sales.manage", "receivables.manage", "inventory.valuation.manage", "finance_core.manage", "finance_core.reverse"),
    "/{plan_id}/review": ("sales.approve", "inventory.valuation.approve", "finance_core.validate", "finance_core.reverse"),
    "/{plan_id}/post": ("sales.manage", "receivables.manage", "inventory.post", "inventory.valuation.approve", "finance_core.post", "finance_core.reverse"),
    "/{plan_id}/cancel": ("sales.approve", "finance_core.validate"),
}.items():
    _CRITICAL_ROUTE_CONTRACTS[("POST", "/api/v1/customer-partial-returns/plans" + _path)] = _erp_contract(_STOCK_READ, *_permissions)

for (_method, _path), _contract in tuple(_CRITICAL_ROUTE_CONTRACTS.items()):
    if _path.startswith("/api/v1/customer-partial-returns/"):
        _CRITICAL_ROUTE_CONTRACTS[(_method, "/api/v2" + _path[len("/api/v1"):])] = _contract

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

# New fixed monetary sources keep their own wire contracts. Pin their complete
# permission surfaces without changing any legacy route or public exemption.
for (_method, _path), _contract in tuple(_CRITICAL_ROUTE_CONTRACTS.items()):
    if _path.startswith("/api/v1/customer-partial-returns/"):
        _CRITICAL_ROUTE_CONTRACTS[(_method, "/api/v3" + _path[len("/api/v1"):])] = _contract
    if _path == "/api/v1/stock-sales/orders" or _path.startswith("/api/v1/stock-sales/orders/"):
        _CRITICAL_ROUTE_CONTRACTS[(_method, "/api/v2" + _path[len("/api/v1"):])] = _contract
for _path in ("/options", "/orders", "/orders/{identifier}"):
    _CRITICAL_ROUTE_CONTRACTS[("GET", "/api/v2/stock-sales" + _path)] = _erp_contract(_STOCK_READ)

# The delegated monetary collection owner needs AR preparation/review rights.
# These stricter unions apply only to the new source version.
for _phase, _permission in (("prepare", "receivables.manage"), ("review", "receivables.approve")):
    _route = ("POST", "/api/v2/stock-sales/orders/{identifier}/collection/" + _phase)
    _CRITICAL_ROUTE_CONTRACTS[_route] = _erp_contract(
        frozenset(_CRITICAL_ROUTE_CONTRACTS[_route][1]), _permission
    )

for _method, _path, _permissions in (
    ("POST", "/valuations", ("finance_core.manage", "receivables.manage")),
    ("POST", "/valuation-reversals", ("finance_core.manage", "finance_core.reverse", "receivables.manage")),
    ("GET", "/fx-plans/{plan_id}", ()),
    ("POST", "/fx-plans/{plan_id}/review", ("finance_core.validate", "receivables.approve")),
    ("POST", "/fx-plans/{plan_id}/post", ("finance_core.post", "receivables.manage")),
):
    _CRITICAL_ROUTE_CONTRACTS[(_method, "/api/v2/stock-sales/orders/{identifier}" + _path)] = _erp_contract(_STOCK_READ, *_permissions)

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
    "/snapshots": "finance_core.read",
    "/maps": "finance_core.manage",
    "/maps/{map_id}/review": "finance_core.validate",
    "/openings": "finance_core.manage",
    "/openings/{opening_id}/review": "finance_core.validate",
    "/openings/{opening_id}/post": "finance_core.post",
}.items():
    _CRITICAL_ROUTE_CONTRACTS[("POST", "/api/v1/financial-reporting" + _path)] = ("all", (_permission,))
for _path, _permission in {"": "finance_core.manage", "/{plan_id}/review": "finance_core.validate", "/{plan_id}/post": "finance_core.post"}.items():
    _CRITICAL_ROUTE_CONTRACTS[("POST", "/api/v1/financial-installments/plans" + _path)] = _erp_contract(frozenset({"payables.settle"}), _permission)

for _path, _permissions in {
    "": ("finance_core.manage", "sales.manage", "receivables.manage"),
    "/{plan_id}/review": ("finance_core.validate", "sales.approve", "receivables.manage"),
    "/{plan_id}/post": ("finance_core.post", "sales.manage", "receivables.manage"),
}.items():
    _CRITICAL_ROUTE_CONTRACTS[("POST", "/api/v1/commercial-collections/plans" + _path)] = _erp_contract(
        frozenset(), *_permissions)
for _path, _permission in {
    "/assets": "finance_core.manage", "/assets/{asset_id}/operations": "finance_core.manage",
    "/plans/{plan_id}/review": "finance_core.validate", "/plans/{plan_id}/post": "finance_core.post",
}.items():
    _CRITICAL_ROUTE_CONTRACTS[("POST", "/api/v1/fixed-assets" + _path)] = ("all", (_permission,))
for _path, _permissions in {
    "": ("payables.manage", "payables.settle", "inventory.manage", "inventory.valuation.manage", "finance_core.manage"),
    "/{identifier}/review": ("payables.approve", "payables.settle", "inventory.post", "inventory.valuation.approve", "finance_core.validate"),
    "/{identifier}/post": ("payables.manage", "payables.settle", "inventory.post", "inventory.valuation.approve", "finance_core.post"),
}.items():
    _CRITICAL_ROUTE_CONTRACTS[("POST", "/api/v1/landed-cost/plans" + _path)] = _erp_contract(
        _PROCUREMENT_READ, *_permissions)



for _method, _path, _operation in (
    ("GET", "/catalog", "read"), ("POST", "/sources", "prepare"), ("GET", "/sources", "read"),
    ("GET", "/sources/{source_id}", "read"), ("POST", "/sources/{source_id}/settlements", "prepare"),
    ("POST", "/sources/{source_id}/eliminations", "prepare"), ("GET", "/plans/{plan_id}", "read"),
    ("POST", "/plans/{plan_id}/review", "review"), ("POST", "/plans/{plan_id}/post", "post"),
    ("GET", "/plans/{plan_id}/evidence", "read"), ("GET", "/sources/{source_id}/report", "read"),
):
    _CRITICAL_ROUTE_CONTRACTS[(_method, "/api/v1/intercompany-operations" + _path)] = (
        "all", tuple(sorted(("intercompany_operations." + _operation,
            "finance_core." + {"read": "read", "prepare": "manage", "review": "validate", "post": "post"}[_operation]))))


_MANUFACTURING_READ = frozenset({"manufacturing_execution.read", "inventory.read", "finance_core.read"})
_MANUFACTURING_OPERATIONS = {
    "read": _MANUFACTURING_READ,
    "create": _MANUFACTURING_READ | {"manufacturing_execution.manage", "inventory.manage"},
    "approve-bom": _MANUFACTURING_READ | {"manufacturing_execution.approve"},
    "prepare": _MANUFACTURING_READ | {"manufacturing_execution.manage", "inventory.manage", "inventory.valuation.manage", "finance_core.manage"},
    "review": _MANUFACTURING_READ | {"manufacturing_execution.approve", "inventory.post", "inventory.valuation.approve", "finance_core.validate"},
    "post": _MANUFACTURING_READ | {"manufacturing_execution.post", "inventory.post", "inventory.valuation.approve", "finance_core.post"},
    "cancel": _MANUFACTURING_READ | {"manufacturing_execution.approve"},
}
for _method, _path, _operation in (
    ("GET", "/orders", "read"), ("POST", "/boms", "create"), ("POST", "/boms/{bom_id}/approve", "approve-bom"),
    ("POST", "/orders", "create"), ("GET", "/orders/{order_id}", "read"),
    ("GET", "/orders/{order_id}/requirements", "read"), ("POST", "/orders/{order_id}/prepare", "prepare"),
    ("POST", "/orders/{order_id}/review", "review"), ("POST", "/orders/{order_id}/post", "post"),
    ("POST", "/orders/{order_id}/cancel", "cancel"), ("POST", "/orders/{order_id}/completions", "prepare"),
    ("POST", "/completions/{completion_id}/review", "review"), ("POST", "/completions/{completion_id}/post", "post"),
    ("POST", "/completions/{completion_id}/cancel", "cancel"),
):
    _CRITICAL_ROUTE_CONTRACTS[(_method, "/api/v1/manufacturing-execution" + _path)] = (
        "all", tuple(sorted(_MANUFACTURING_OPERATIONS[_operation])))


_SOURCING_READ = frozenset({"procurement_sourcing.read", "budget_control.read", "payables.read", "inventory.read", "finance_core.read"})
for _method, _path, _sourcing_permissions in (
    ("GET", "/requisitions", frozenset()), ("GET", "/requisitions/{identifier}", frozenset()),
    ("POST", "/requisitions", frozenset({"procurement_sourcing.manage"})),
    ("POST", "/requisitions/{identifier}/quotes", frozenset({"procurement_sourcing.manage"})),
    ("POST", "/requisitions/{identifier}/award", frozenset({"procurement_sourcing.award", "budget_control.manage", "payables.manage"})),
    ("POST", "/requisitions/{identifier}/open-rfq", frozenset({"procurement_sourcing.approve"})),
    ("POST", "/requisitions/{identifier}/review-selection", frozenset({"procurement_sourcing.approve"})),
    ("POST", "/requisitions/{identifier}/cancel", frozenset({"procurement_sourcing.approve"})),
):
    _CRITICAL_ROUTE_CONTRACTS[(_method, "/api/v1/procurement-sourcing" + _path)] = (
        "all", tuple(sorted(_SOURCING_READ | _sourcing_permissions)))


for _method, _path, _phase in (
    ("GET", "/orders", "read"), ("GET", "/orders/{identifier}", "read"),
    ("POST", "/workcenters", "create"), ("POST", "/routings", "create"),
    ("POST", "/definitions/{identifier}/approve", "approve-bom"), ("POST", "/orders", "create"),
    ("POST", "/orders/{identifier}/prepare", "prepare"), ("POST", "/orders/{identifier}/review", "review"),
    ("POST", "/orders/{identifier}/post", "post"), ("POST", "/orders/{identifier}/cancel", "cancel"),
    ("POST", "/orders/{identifier}/productions", "prepare"), ("POST", "/productions/{identifier}/review", "review"),
    ("POST", "/productions/{identifier}/post", "post"), ("POST", "/productions/{identifier}/cancel", "cancel"),
    ("POST", "/productions/{identifier}/inspections", "prepare"), ("POST", "/inspections/{identifier}/review", "review"),
    ("POST", "/inspections/{identifier}/post", "post"), ("POST", "/inspections/{identifier}/cancel", "cancel"),
):
    _v2_permissions = _MANUFACTURING_OPERATIONS[_phase] | {"manufacturing_execution_v2.read"}
    if _phase != "read":
        _v2_permissions = _v2_permissions | {"manufacturing_execution_v2." +
            {"create": "manage", "prepare": "manage", "review": "approve", "post": "post", "cancel": "approve", "approve-bom": "approve"}[_phase]}
    _CRITICAL_ROUTE_CONTRACTS[(_method, "/api/v1/manufacturing-execution-v2" + _path)] = ("all", tuple(sorted(_v2_permissions)))


for _method, _path, _phase in (
    ("GET", "/catalog", "read"), ("POST", "/sources", "prepare"), ("GET", "/sources", "read"),
    ("GET", "/sources/{source_id}", "read"), ("POST", "/sources/{source_id}/settlements", "prepare"),
    ("POST", "/sources/{source_id}/revaluations", "prepare"),
    ("POST", "/sources/{source_id}/revaluation-reversals", "reverse"),
    ("POST", "/sources/{source_id}/eliminations", "prepare"), ("GET", "/plans/{plan_id}", "read"),
    ("POST", "/plans/{plan_id}/review", "review"), ("POST", "/plans/{plan_id}/post", "post"),
    ("GET", "/plans/{plan_id}/evidence", "read"), ("GET", "/sources/{source_id}/report", "read"),
):
    _icfx_permissions = {"intercompany_fx." + ("prepare" if _phase == "reverse" else _phase),
                    "finance_core." + {"read": "read", "prepare": "manage", "review": "validate", "post": "post", "reverse": "manage"}[_phase]}
    if _phase == "reverse":
        _icfx_permissions.add("finance_core.reverse")
    _CRITICAL_ROUTE_CONTRACTS[(_method, "/api/v1/intercompany-fx" + _path)] = ("all", tuple(sorted(_icfx_permissions)))


_CRITICAL_ROUTE_CONTRACTS[("GET", "/api/v1/intercompany-fx/sources/{source_id}/native-evidence-bundle")] = (
    "all", ("finance_core.read", "intercompany_fx.read"),
)

for _cashflow_path in ("/sources/{source_id}", "/sources/{source_id}/evidence/export"):
    _CRITICAL_ROUTE_CONTRACTS[("GET", "/api/v1/intercompany-source-cashflow" + _cashflow_path)] = (
        "all", ("finance_core.read", "intercompany_fx.read"),
    )

for _group_path in ("/report", "/evidence"):
    _CRITICAL_ROUTE_CONTRACTS[("GET", "/api/v1/intercompany-group-diagnostic" + _group_path)] = (
        "all", ("finance_core.read", "intercompany_fx.read"),
    )

for _project_source_path in ("/report", "/evidence", "/close-diagnostics", "/close-diagnostics/evidence"):
    _CRITICAL_ROUTE_CONTRACTS[("GET", "/api/v1/project-source-reconciliation" + _project_source_path)] = (
        "all", ("finance_core.read", "people_project_payroll.read", "project_time_billing.read", "receivables.read"),
    )


for _method, _path, _phase in (
    ("GET", "/catalog", "read"), ("GET", "/sources", "read"), ("GET", "/sources/{source_id}", "read"),
    ("GET", "/sources/{source_id}/evidence", "read"), ("GET", "/plans/{plan_id}", "read"),
    ("GET", "/sources/{source_id}/evidence/export", "read"), ("GET", "/plans/{plan_id}/evidence/export", "read"),
    ("POST", "/sources", "prepare"), ("POST", "/sources/{source_id}/tranches", "prepare"),
    ("POST", "/sources/{source_id}/cancellations", "prepare"), ("POST", "/sources/{source_id}/reversals", "reverse"),
    ("POST", "/plans/{plan_id}/review", "review"), ("POST", "/plans/{plan_id}/post", "post"),
):
    _schedule_permissions = {"accrual_deferral." + ("prepare" if _phase == "reverse" else _phase),
                            "finance_core." + {"read": "read", "prepare": "manage", "review": "validate", "post": "post", "reverse": "manage"}[_phase]}
    if _phase == "reverse":
        _schedule_permissions.add("finance_core.reverse")
    _CRITICAL_ROUTE_CONTRACTS[(_method, "/api/v1/accrual-deferral" + _path)] = ("all", tuple(sorted(_schedule_permissions)))

_SUPPLY_READ_CONTRACT = frozenset({"manufacturing_supply_plan.read", "manufacturing_execution_v2.read",
    "manufacturing_execution.read", "inventory.read", "finance_core.read", "budget_control.read"})
_SUPPLY_PHASE_ADDITIONS = {
    "read": (), "create": ("manufacturing_supply_plan.manage",),
    "approve": ("manufacturing_supply_plan.approve", "inventory.manage"),
    "cancel": ("manufacturing_supply_plan.approve", "inventory.manage"),
    "handoff": ("manufacturing_supply_plan.manage", "inventory.manage", "manufacturing_execution.manage", "manufacturing_execution_v2.manage"),
    "source-create": ("manufacturing_supply_plan.manage", "procurement_sourcing.manage", "procurement_sourcing.read", "payables.read"),
    "source-quote": ("manufacturing_supply_plan.manage", "procurement_sourcing.manage", "procurement_sourcing.read", "payables.read"),
    "source-open-rfq": ("manufacturing_supply_plan.approve", "procurement_sourcing.approve", "procurement_sourcing.read", "payables.read"),
    "source-review-selection": ("manufacturing_supply_plan.approve", "procurement_sourcing.approve", "procurement_sourcing.read", "payables.read"),
    "source-cancel": ("manufacturing_supply_plan.approve", "procurement_sourcing.approve", "procurement_sourcing.read", "payables.read"),
    "source-award": ("manufacturing_supply_plan.post", "procurement_sourcing.award", "procurement_sourcing.read", "payables.manage", "payables.read", "budget_control.manage"),
    "purchase-submit": ("manufacturing_supply_plan.manage", "budget_control.manage", "payables.manage"),
    "purchase-approve": ("manufacturing_supply_plan.approve", "budget_control.manage", "payables.approve"),
    "receive-prepare": ("manufacturing_supply_plan.manage", "budget_control.manage", "payables.manage", "inventory.manage", "inventory.valuation.manage", "finance_core.manage"),
    "receive-review": ("manufacturing_supply_plan.approve", "budget_control.manage", "payables.approve", "inventory.post", "inventory.valuation.approve", "finance_core.validate"),
    "receive-commit": ("manufacturing_supply_plan.post", "budget_control.manage", "payables.manage", "inventory.post", "inventory.valuation.approve", "finance_core.post"),
    "invoice-match": ("manufacturing_supply_plan.manage", "budget_control.manage", "payables.manage", "payables.match"),
    "invoice-approve": ("manufacturing_supply_plan.approve", "budget_control.manage", "payables.approve"),
    "invoice-prepare": ("manufacturing_supply_plan.manage", "budget_control.manage", "payables.manage", "finance_core.manage"),
    "invoice-review": ("manufacturing_supply_plan.approve", "budget_control.manage", "payables.approve", "finance_core.validate"),
    "invoice-post": ("manufacturing_supply_plan.post", "budget_control.manage", "payables.approve", "finance_core.post"),
}
for _method, _path, _phase in (
    ("GET", "/plans", "read"), ("GET", "/plans/{identifier}", "read"),
    ("GET", "/requirements/{identifier}", "read"),
    ("GET", "/plans/{identifier}/requisitions/{requisition_id}", "read"),
    ("GET", "/plans/{identifier}/purchases/{order_id}", "read"),
    ("POST", "/plans", "create"), ("POST", "/plans/{identifier}/approve", "approve"),
    ("POST", "/plans/{identifier}/cancel", "cancel"), ("POST", "/plans/{identifier}/handoff", "handoff"),
    ("POST", "/plans/{identifier}/requisitions", "source-create"),
    *(("POST", "/plans/{identifier}/requisitions/{requisition_id}/" + action, "source-" + action)
      for action in ("open-rfq", "quote", "review-selection", "award", "cancel")),
    *(("POST", "/plans/{identifier}/purchases/{order_id}/" + action, action)
      for action in ("purchase-submit", "purchase-approve", "receive-prepare", "receive-review", "receive-commit",
                     "invoice-match", "invoice-approve", "invoice-prepare", "invoice-review", "invoice-post")),
):
    _CRITICAL_ROUTE_CONTRACTS[(_method, "/api/v1/manufacturing-supply-plan" + _path)] = (
        "all", tuple(sorted(_SUPPLY_READ_CONTRACT | set(_SUPPLY_PHASE_ADDITIONS[_phase]))))

_TRANSFER_READ_CONTRACT = frozenset({"inventory_transfer.read", "inventory.read", "inventory.valuation.read", "finance_core.read"})
for _method, _path, _additional in (
    ("GET", "/transfers", ()), ("GET", "/transfers/{identifier}", ()),
    ("GET", "/transfers/{identifier}/evidence", ()),
    ("POST", "/transfers", ("inventory_transfer.manage", "inventory.manage")),
    ("POST", "/transfers/{identifier}/inverse", ("inventory_transfer.manage", "inventory.manage")),
    ("POST", "/transfers/{identifier}/review", ("inventory_transfer.approve", "inventory.manage")),
    ("POST", "/transfers/{identifier}/cancel", ("inventory_transfer.approve", "inventory.manage")),
    ("POST", "/transfers/{identifier}/post", ("inventory_transfer.post", "inventory.post")),
):
    _CRITICAL_ROUTE_CONTRACTS[(_method, "/api/v1/inventory-transfer" + _path)] = (
        "all", tuple(sorted(_TRANSFER_READ_CONTRACT | set(_additional))))

_PEOPLE_PHASE_CONTRACTS = {
    "personnel": frozenset({"people_project_payroll.personnel", "people_project_payroll.read_sensitive"}),
    "manage": frozenset({"people_project_payroll.manage"}),
    "approve_time": frozenset({"people_project_payroll.approve_time"}),
    "prepare": frozenset({"people_project_payroll.prepare", "people_project_payroll.read_sensitive", "finance_core.manage", "budget_control.read", "budget_control.manage"}),
    "review": frozenset({"people_project_payroll.review", "people_project_payroll.read_sensitive", "finance_core.validate", "budget_control.read"}),
    "post": frozenset({"people_project_payroll.post", "people_project_payroll.read_sensitive", "finance_core.post", "budget_control.read", "budget_control.manage"}),
    "pay": frozenset({"people_project_payroll.pay", "people_project_payroll.read_sensitive", "finance_core.manage", "budget_control.read"}),
    "read": frozenset({"people_project_payroll.read"}),
    "read_sensitive": frozenset({"people_project_payroll.read", "people_project_payroll.read_sensitive", "finance_core.read"}),
}
_PROJECT_BILLING_PHASE_CONTRACTS = {
    "read": frozenset({"project_time_billing.read"}),
    "evidence": frozenset({"project_time_billing.read", "finance_core.read", "people_project_payroll.read", "receivables.read"}),
    "manage": frozenset({"project_time_billing.manage", "receivables.read"}),
    "approve_price": frozenset({"project_time_billing.approve_price"}),
    "prepare": frozenset({"project_time_billing.prepare", "finance_core.manage", "receivables.manage", "people_project_payroll.read"}),
    "collect": frozenset({"project_time_billing.collect", "finance_core.manage", "receivables.receive"}),
    "review": frozenset({"project_time_billing.review", "finance_core.validate", "receivables.manage"}),
    "post": frozenset({"project_time_billing.post", "finance_core.post", "receivables.approve", "receivables.receive"}),
}
for _method, _path, _phase in (
    ("POST", "/prices", "manage"), ("POST", "/prices/{price_id}/approve", "approve_price"),
    ("POST", "/invoices", "prepare"), ("POST", "/invoices/{invoice_id}/collections", "collect"),
    ("POST", "/plans/{plan_id}/review", "review"), ("POST", "/plans/{plan_id}/post", "post"),
    ("POST", "/plans/{plan_id}/cancel", "prepare"), ("GET", "/plans/{plan_id}", "evidence"),
    ("GET", "/invoices/{invoice_id}/evidence", "evidence"), ("GET", "/catalog", "evidence"),
):
    _CRITICAL_ROUTE_CONTRACTS[(_method, "/api/v1/project-time-billing" + _path)] = (
        "all", tuple(sorted(_PROJECT_BILLING_PHASE_CONTRACTS[_phase])))

for _method, _path, _phase in (
    ("POST", "/employees", "personnel"), ("POST", "/employees/{employee_id}/employment", "personnel"),
    ("POST", "/projects", "manage"), ("POST", "/times", "manage"), ("POST", "/times/{time_id}/approve", "approve_time"),
    ("POST", "/payruns", "prepare"), ("POST", "/payruns/{payrun_id}/payments", "pay"),
    ("POST", "/plans/{plan_id}/review", "review"), ("POST", "/plans/{plan_id}/post", "post"),
    ("POST", "/payruns/{payrun_id}/cancel", "prepare"), ("GET", "/plans/{plan_id}", "read"),
    ("GET", "/plans/{plan_id}/private", "read_sensitive"), ("GET", "/payruns/{payrun_id}/evidence", "read_sensitive"),
    ("GET", "/catalog/{kind}", "read"),
):
    _CRITICAL_ROUTE_CONTRACTS[(_method, "/api/v1/people-project-payroll" + _path)] = (
        "all", tuple(sorted(_PEOPLE_PHASE_CONTRACTS[_phase])))


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
        expected = _CRITICAL_ROUTE_CONTRACTS.get(key)
        if expected is not None and (contract.mode, contract.permissions) != expected:
            raise ValueError(
                "Critical API route authorization contract drifted: "
                f"{contract.method} {contract.path} expected {expected}, "
                f"got {(contract.mode, contract.permissions)}."
            )
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
