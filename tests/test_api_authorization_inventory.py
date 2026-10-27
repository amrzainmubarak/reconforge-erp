from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import APIRouter

from reconforge.api import create_api_app
from reconforge.api.authorization import (
    RouteAuthorizationContract,
    authorization_inventory_digest,
    build_route_authorization_inventory,
    validate_authorization_surface,
)
from reconforge.api.dependencies import require_any_permission, require_permission

EXPECTED_ROUTE_COUNT = 492
EXPECTED_DIGEST = "14b516ccedc6622f05971c891af1ab1764ca1c31994aa5c22855b939c074cf83"
ENTERPRISE_M1_PREFIXES = (
    "/api/v1/manufacturing-execution-v2/", "/api/v1/intercompany-fx/", "/api/v1/people-project-payroll/",
)
EXPECTED_ENTERPRISE_M1_ROUTE_COUNT = 45
ENTERPRISE_M2_PREFIXES = ("/api/v1/accrual-deferral/", "/api/v1/project-time-billing/", "/api/v1/manufacturing-supply-plan/")
EXPECTED_ENTERPRISE_M2_ROUTE_COUNT = 48
ENTERPRISE_M3_PREFIXES = ("/api/v1/intercompany-source-cashflow/", "/api/v1/project-source-reconciliation/", "/api/v1/intercompany-group-diagnostic/")
ENTERPRISE_M3_EXACT_ROUTES = frozenset({
    ("GET", "/api/v1/intercompany-fx/sources/{source_id}/native-evidence-bundle"),
})
EXPECTED_ENTERPRISE_M3_ROUTE_COUNT = 9
ENTERPRISE_M4_PREFIXES = ("/api/v1/inventory-transfer/",)
EXPECTED_ENTERPRISE_M4_ROUTE_COUNT = 8
MONETARY_M7_PREFIXES = ("/api/v2/stock-sales/", "/api/v3/customer-partial-returns/")
ENTERPRISE_M7_PREFIXES = ("/api/v1/customer-partial-returns/", "/api/v2/customer-partial-returns/", *MONETARY_M7_PREFIXES)
EXPECTED_ENTERPRISE_M7_ROUTE_COUNT = 49
WAVE5_PREFIXES = ("/api/v1/manufacturing-execution/", "/api/v1/intercompany-operations/", "/api/v1/procurement-sourcing/")
WAVE4_PREFIXES = (
    "/api/v1/customer-returns/", "/api/v1/procurement-commitments/",
    "/api/v1/operational-fx-tax/", "/api/v1/supplier-returns/",
)
# Exact new enterprise cohort, independent of runtime enumeration. Historical
# counts and digests below remain untouched; an unlisted route is not excluded.
def _enterprise_contracts() -> tuple[RouteAuthorizationContract, ...]:
    rows: list[RouteAuthorizationContract] = []

    def group(prefix: str, mode: str, permissions: tuple[str, ...], routes: tuple[tuple[str, str], ...]) -> None:
        rows.extend(
            RouteAuthorizationContract(method, "/api/v1" + prefix + path, mode, tuple(sorted(permissions)))
            for method, path in routes
        )

    group(
        "/crm/contracts",
        "all",
        ("sales.manage",),
        (
            ("GET", "/contracts/{contract_id}"),
            ("GET", "/opportunities/{opportunity_id}"),
            ("GET", "/quotations/{quote_id}"),
            ("GET", "/subscriptions"),
            ("GET", "/subscriptions/plans"),
            ("GET", "/subscriptions/plans/{plan_id}"),
            ("GET", "/subscriptions/{subscription_id}"),
            ("POST", "/contracts/{contract_id}/resume"),
            ("POST", "/contracts/{contract_id}/suspend"),
            ("POST", "/contracts/{contract_id}/terminate"),
            ("POST", "/opportunities"),
            ("POST", "/quotations"),
            ("POST", "/quotations/{quote_id}/convert"),
            ("POST", "/subscriptions"),
            ("POST", "/subscriptions/plans"),
            ("POST", "/subscriptions/proration"),
            ("POST", "/subscriptions/{subscription_id}/cancel"),
        ),
    )
    group(
        "/crm/contracts",
        "all",
        ("sales.approve",),
        (("POST", "/contracts/{contract_id}/renew"), ("POST", "/quotations/{quote_id}/approve")),
    )
    group(
        "/finance/consolidated-statements",
        "any",
        ("finance_core.manage", "finance_core.read"),
        (("GET", "/runs"), ("GET", "/runs/{run_id}")),
    )
    group("/finance/consolidated-statements", "all", ("finance_core.manage",), (("POST", "/generate"),))
    group(
        "/hcm/leave",
        "all",
        ("people_project_payroll.personnel",),
        (
            ("GET", "/balances/{employee_id}/{leave_type}"),
            ("GET", "/requests/{request_id}"),
            ("POST", "/requests"),
            ("POST", "/requests/{request_id}/unpaid-deduction"),
            ("POST", "/requests/{request_id}/withdraw"),
        ),
    )
    group(
        "/hcm/leave",
        "all",
        ("people_project_payroll.manage",),
        (
            ("POST", "/balances"),
            ("POST", "/balances/{employee_id}/{leave_type}/accrue-prorated"),
            ("POST", "/balances/{employee_id}/{leave_type}/rollover"),
            ("POST", "/requests/{request_id}/cancel"),
        ),
    )
    group(
        "/hcm/leave",
        "all",
        ("people_project_payroll.approve_time",),
        (("POST", "/requests/{request_id}/approve"), ("POST", "/requests/{request_id}/reject")),
    )
    group(
        "/intercompany/eliminations",
        "any",
        ("finance_core.manage", "finance_core.read"),
        (("GET", "/profit-in-stock"), ("GET", "/runs"), ("GET", "/runs/{run_id}")),
    )
    group(
        "/intercompany/eliminations",
        "all",
        ("finance_core.manage",),
        (("POST", "/profit-in-stock"), ("POST", "/propose")),
    )
    group(
        "/manufacturing/bom",
        "all",
        ("manufacturing_execution.read",),
        (("GET", "/{item_id}"), ("POST", "/explode"), ("POST", "/net-requirements")),
    )
    group("/manufacturing/bom", "all", ("manufacturing_execution.manage",), (("POST", ""),))
    group(
        "/manufacturing/capacity",
        "all",
        ("manufacturing_execution.read",),
        (("GET", "/calendars"), ("GET", "/calendars/{workcenter_id}"), ("GET", "/reservations")),
    )
    group(
        "/manufacturing/capacity",
        "all",
        ("manufacturing_execution.manage",),
        (
            ("POST", "/calendars"),
            ("POST", "/reservations"),
            ("POST", "/reservations/reschedule"),
            ("DELETE", "/reservations/{work_order_id}/{operation_sequence}"),
        ),
    )
    group(
        "/manufacturing/quality",
        "all",
        ("manufacturing_execution.read",),
        (("GET", "/inspection-plans/{item_id}"), ("POST", "/evaluate")),
    )
    group(
        "/manufacturing/quality",
        "all",
        ("manufacturing_execution.manage",),
        (
            ("POST", "/inspection-plans"),
            ("POST", "/ncrs"),
            ("POST", "/ncrs/{ncr_id}/disposition"),
            ("POST", "/rework-orders"),
            ("POST", "/rework-orders/{rework_order_id}/log-step"),
            ("POST", "/rework-orders/{rework_order_id}/complete"),
        ),
    )
    group(
        "/manufacturing/mps",
        "any",
        ("manufacturing_supply_plan.manage", "manufacturing_supply_plan.read"),
        (("GET", "/plans"), ("GET", "/plans/{plan_id}/{revision}"), ("GET", "/requisitions")),
    )
    group("/manufacturing/mps", "all", ("manufacturing_supply_plan.manage",), (("POST", "/compute"),))
    group(
        "/manufacturing/traceability",
        "any",
        ("manufacturing_execution.manage", "manufacturing_execution.read"),
        (
            ("GET", "/dispatches/{dispatch_id}"),
            ("GET", "/genealogy/backward/{lot_id}"),
            ("GET", "/genealogy/forward/{lot_id}"),
            ("GET", "/lots/{lot_id}"),
        ),
    )
    group(
        "/manufacturing/traceability",
        "all",
        ("manufacturing_execution.manage",),
        (("POST", "/dispatch"), ("POST", "/lots"), ("POST", "/steps/progress")),
    )
    group(
        "/projects/billing",
        "any",
        ("project_time_billing.manage", "project_time_billing.read"),
        (("GET", "/milestones/{milestone_id}"), ("GET", "/summary/{project_id}"), ("GET", "/tasks/{project_id}")),
    )
    group(
        "/projects/billing",
        "all",
        ("project_time_billing.manage",),
        (
            ("POST", "/milestones"),
            ("POST", "/milestones/{milestone_id}/verify"),
            ("POST", "/rate-cards"),
            ("POST", "/tasks"),
            ("POST", "/time-logs"),
        ),
    )
    group("/projects/billing", "all", ("project_time_billing.manage", "finance_core.manage"), (("POST", "/milestones/{milestone_id}/bill"),))
    group("/projects/billing", "all", ("project_time_billing.read", "finance_core.read"), (("GET", "/finance/{binding_id}"),))
    group("/projects/billing", "all", ("project_time_billing.review", "finance_core.validate"), (("POST", "/finance/{binding_id}/review"),))
    group("/projects/billing", "all", ("project_time_billing.post", "finance_core.post"), (("POST", "/finance/{binding_id}/post"),))
    group("/projects/billing", "all", ("project_time_billing.manage", "finance_core.manage", "finance_core.reverse"), (("POST", "/finance/{binding_id}/reversal"),))
    group("/intercompany/eliminations", "all", ("finance_core.read",), (("GET", "/finance/{binding_id}"),))
    group("/intercompany/eliminations", "all", ("finance_core.validate",), (("POST", "/finance/{binding_id}/review"),))
    group("/intercompany/eliminations", "all", ("finance_core.post",), (("POST", "/finance/{binding_id}/post"),))
    group("/intercompany/eliminations", "all", ("finance_core.manage", "finance_core.reverse"), (("POST", "/finance/{binding_id}/reversal"),))
    group("/treasury", "all", ("finance_core.read",), (("GET", "/positions/{bank_account_id}"), ("POST", "/forecast")))
    group("/treasury", "all", ("finance_core.manage",), (("POST", "/flows"), ("POST", "/positions")))
    group("/ai/assistant", "any", ("ai.query", "finance_core.read"), (("POST", "/query"),))
    return tuple(sorted(rows))


ENTERPRISE_V1_CONTRACTS = _enterprise_contracts()
ENTERPRISE_V1_KEYS = frozenset((row.method, row.path) for row in ENTERPRISE_V1_CONTRACTS)


def _retained_before_enterprise(
    contracts: tuple[RouteAuthorizationContract, ...],
) -> tuple[RouteAuthorizationContract, ...]:
    return tuple(row for row in contracts if (row.method, row.path) not in ENTERPRISE_V1_KEYS)


def test_enterprise_v1_additions_have_exact_reviewed_permissions(tmp_path: Path) -> None:
    contracts = create_api_app(tmp_path / "unused.db").state.authorization_contracts
    actual = tuple(row for row in contracts if (row.method, row.path) in ENTERPRISE_V1_KEYS)
    assert len(ENTERPRISE_V1_KEYS) == len(ENTERPRISE_V1_CONTRACTS) == 90
    assert actual == ENTERPRISE_V1_CONTRACTS



ROUTES_ROOT = Path(__file__).parents[1] / "reconforge" / "api" / "routes"
SPECIAL_ROUTE_MODULES = frozenset(
    {
        # Authentication and protocol surfaces have their own explicit
        # handshake or SCIM authorization classification.
        "auth.py",
        "scim.py",
        "webauthn.py",
    }
)
SERVER_BOUNDARY_MARKERS = (
    "enforce_server_scoped",
    "enforce_server_tenant",
    "server_identity_enabled",
)
HANDLER_BOUNDARY_HELPERS = {
    "consolidated_financial_statements.py": frozenset({"_get_repository"}),
    "crm_contracts.py": frozenset({"_repo"}),
    "governed_assistant.py": frozenset({"enterprise_transaction"}),
    "hcm_leave.py": frozenset({"_repo"}),
    "intercompany_elimination.py": frozenset({"_get_repository"}),
    "manufacturing_bom.py": frozenset({"_get_repository"}),
    "manufacturing_capacity.py": frozenset({"_get_repository"}),
    "manufacturing_quality.py": frozenset({"_repository"}),
    "master_production_schedule.py": frozenset({"_get_repository"}),
    "project_milestone_billing.py": frozenset({"_get_repo"}),
    "shop_floor_traceability.py": frozenset({"_get_repo"}),
    "treasury_liquidity.py": frozenset({"_repo"}),

    "access_administration.py": frozenset({"_service"}),
    "accounts.py": frozenset({"_server_scope"}),
    "consolidation_deferred_tax.py": frozenset({"_enforce_server_policy"}),
    "consolidation_impairment.py": frozenset({"_enforce_server_policy"}),
    "consolidation_intercompany.py": frozenset({"_scope_for_payload", "_server_only"}),
    "consolidation_ownership_change.py": frozenset({"_enforce_server_policy"}),
    "consolidation_ppa.py": frozenset({"_enforce_server_policy"}),
    "emergency_access.py": frozenset({"_execute"}),
    "exceptions.py": frozenset({"_local_connection", "_server_scope"}),
    "evidence.py": frozenset({"_enforce_server_evidence_permission"}),
    "finance_core.py": frozenset({"_server_finance_workspace"}),
    "finance_posting.py": frozenset({"_authority"}),
    "durable_job_operations.py": frozenset({"_command"}),
    "inventory_receipt_posting.py": frozenset({"_execute"}),
    "intercompany_operations.py": frozenset({"authority", "execute"}),
    "intercompany_fx.py": frozenset({"authority", "execute"}),
    "intercompany_cashflow.py": frozenset({"capture"}),
    "intercompany_group_diagnostic.py": frozenset({"capture"}),
    "project_source_reconciliation.py": frozenset({"capture"}),
    "accrual_deferral.py": frozenset({"authority", "execute"}),
    "project_time_billing.py": frozenset({"execute", "phase"}),
    "manufacturing_supply_plan.py": frozenset({"execute"}),
    "inventory_transfer.py": frozenset({"execute"}),
    # Reviewed HC execution chooses only the ordinary scoped GL transaction or
    # the separate role-authenticated personnel transaction; HTTP cannot select it.
    "people_project_payroll.py": frozenset({"execute"}),
    "manufacturing_execution.py": frozenset({"execute", "order_phase", "completion_phase"}),
    "manufacturing_execution_v2.py": frozenset({"execute", "phase"}),
    "procurement_sourcing.py": frozenset({"_execute"}),
    "operational_finance.py": frozenset({"_authority", "_execute"}),
    "sales_revenue.py": frozenset({"_execute", "_transition"}),
    "procurement_operations.py": frozenset({"execute"}),
    "stock_sales.py": frozenset({"_execute", "_transition", "_commerce_execute"}),
    # Both command families enter the same scoped ordinary PostgreSQL owner;
    # valuation supplies its stricter exact permission union and closed projector.
    "stock_sales_v2.py": frozenset({"execute", "execute_valuation", "_transition"}),
    "procurement_partial.py": frozenset({"_execute"}),
    "financial_reporting.py": frozenset({"_execute"}),
    "financial_installments.py": frozenset({"execute", "_authority"}),
    # New source owners reuse verified PostgreSQL identity, scoped ABAC and the
    # caller-owned transaction; no implicit local financial fallback is admitted.
    "commercial_collections.py": frozenset({"execute", "_authority"}),
    "landed_cost.py": frozenset({"execute"}),
    "fixed_assets.py": frozenset({"execute", "_authority"}),
    "customer_returns.py": frozenset({"execute", "_authority"}),
    "customer_partial_returns.py": frozenset({"execute", "_authority"}),
    "customer_partial_returns_v3.py": frozenset({"execute"}),
    "procurement_commitments.py": frozenset({"_execute", "_authority"}),
    "supplier_returns.py": frozenset({"_execute"}),
    "operational_fx_tax.py": frozenset({"execute", "_authority"}),
    "identity_administration.py": frozenset({"_service"}),
    "inventory_core.py": frozenset({"_server_call"}),
    "inventory_planning.py": frozenset({"_server_call"}),
    "inventory_valuation.py": frozenset({"_server_call"}),
    "inventory_valuation_reversal.py": frozenset({"_server_call"}),
    "master_data.py": frozenset({"_enforce_server_manage"}),
    # `_call` dispatches every mutating inbox handler through the reviewed
    # server identity boundary, while retaining the explicitly local-only
    # SQLite path for Community mode.
    "notification_inbox.py": frozenset({"_call"}),
    # `_call` derives a current local human principal or opens the selected
    # PostgreSQL tenant scope before each budget mutation.
    "budget_control.py": frozenset({"_call"}),
    "payables.py": frozenset({"_server_call"}),
    "receivables.py": frozenset({"_server_call"}),
    "reconciliation.py": frozenset({"_enforce_server_run_scope"}),
    "security_governance.py": frozenset({"_service"}),
    "users.py": frozenset({"_local_connection"}),
    "workflow.py": frozenset({"_local_connection"}),
}


def test_api_authorization_inventory_is_closed_and_digest_addressed(tmp_path: Path) -> None:
    app = create_api_app(tmp_path / "unused.db")
    contracts = app.state.authorization_contracts
    contracts = _retained_before_enterprise(contracts)

    retained = tuple(contract for contract in contracts if not contract.path.startswith(ENTERPRISE_M1_PREFIXES + ENTERPRISE_M2_PREFIXES + ENTERPRISE_M3_PREFIXES + ENTERPRISE_M4_PREFIXES + ENTERPRISE_M7_PREFIXES))
    assert len(retained) == EXPECTED_ROUTE_COUNT
    assert authorization_inventory_digest(retained) == EXPECTED_DIGEST
    assert len(contracts) == EXPECTED_ROUTE_COUNT + EXPECTED_ENTERPRISE_M1_ROUTE_COUNT + EXPECTED_ENTERPRISE_M2_ROUTE_COUNT + EXPECTED_ENTERPRISE_M3_ROUTE_COUNT + EXPECTED_ENTERPRISE_M4_ROUTE_COUNT + EXPECTED_ENTERPRISE_M7_ROUTE_COUNT
    assert app.state.authorization_contract_digest == authorization_inventory_digest(app.state.authorization_contracts)
    assert len(app.state.authorization_contracts) == len(contracts) + len(ENTERPRISE_V1_CONTRACTS)
    assert {contract.mode for contract in contracts} == {"all", "any", "dynamic", "identity", "public", "scim"}
    assert [contract for contract in contracts if contract.mode == "dynamic"] == [
        next(
            contract
            for contract in contracts
            if contract.method == "POST"
            and contract.path == "/api/v1/workflow/objects/{object_type}/{object_id}/transition"
        )
    ]
    assert all(contract.permissions for contract in contracts if contract.mode in {"all", "any"})


def test_enterprise_route_cohorts_retain_historical_m1_and_classify_exact_m3_addition(tmp_path: Path) -> None:
    contracts = create_api_app(tmp_path / "unused.db").state.authorization_contracts
    contracts = _retained_before_enterprise(contracts)
    m1 = tuple(contract for contract in contracts if contract.path.startswith(ENTERPRISE_M1_PREFIXES)
               and (contract.method, contract.path) not in ENTERPRISE_M3_EXACT_ROUTES)
    m3 = tuple(contract for contract in contracts if contract.path.startswith(ENTERPRISE_M3_PREFIXES)
               or (contract.method, contract.path) in ENTERPRISE_M3_EXACT_ROUTES)
    assert len(m1) == EXPECTED_ENTERPRISE_M1_ROUTE_COUNT == 45
    assert len(m3) == EXPECTED_ENTERPRISE_M3_ROUTE_COUNT == 9
    m4 = tuple(contract for contract in contracts if contract.path.startswith(ENTERPRISE_M4_PREFIXES))
    assert len(m4) == EXPECTED_ENTERPRISE_M4_ROUTE_COUNT == 8
    transfer_reads = {"inventory_transfer.read", "inventory.read", "inventory.valuation.read", "finance_core.read"}
    assert all(contract.mode == "all" and transfer_reads <= set(contract.permissions) for contract in m4)
    assert {(contract.method, contract.path) for contract in m1}.isdisjoint(
        {(contract.method, contract.path) for contract in m3})
    assert len([contract for contract in contracts if contract.mode == "scim"]) == 15
    emergency_request = next(
        contract
        for contract in contracts
        if contract.method == "POST" and contract.path == "/api/v1/auth/emergency-access/requests"
    )
    assert emergency_request.mode == "all"
    assert emergency_request.permissions == ("security.emergency.request",)
    grouped_aging = next(
        contract for contract in contracts
        if contract.method == "GET" and contract.path == "/api/v1/receivables/aging-by-currency"
    )
    assert grouped_aging.mode == "any"
    assert grouped_aging.permissions == (
        "receivables.approve", "receivables.credit_override", "receivables.manage", "receivables.read",
    )
    payment_link_write = next(
        contract
        for contract in contracts
        if contract.method == "POST"
        and contract.path == "/api/v1/payables/invoices/{invoice_id}/payment-links"
    )
    assert payment_link_write.mode == "all"
    assert payment_link_write.permissions == ("payables.settle",)
    payment_link_read = next(
        contract
        for contract in contracts
        if contract.method == "GET"
        and contract.path == "/api/v1/payables/invoices/{invoice_id}/payment-links"
    )
    assert payment_link_read.mode == "any"
    assert payment_link_read.permissions == (
        "payables.approve", "payables.manage", "payables.match", "payables.read", "payables.reverse", "payables.settle",
    )
    payment_link_reversal_write = next(
        contract
        for contract in contracts
        if contract.method == "POST"
        and contract.path == "/api/v1/payables/invoices/{invoice_id}/payment-links/{payment_link_id}/reversal"
    )
    assert payment_link_reversal_write.mode == "all"
    assert payment_link_reversal_write.permissions == ("payables.reverse",)
    payment_link_reversal_read = next(
        contract
        for contract in contracts
        if contract.method == "GET"
        and contract.path == "/api/v1/payables/invoices/{invoice_id}/payment-link-reversals"
    )
    assert payment_link_reversal_read.mode == "any"
    assert payment_link_reversal_read.permissions == (
        "payables.approve", "payables.manage", "payables.match", "payables.read", "payables.reverse", "payables.settle",
    )
    validate_authorization_surface(contracts)


def test_fixed_monetary_routes_preserve_all_620_retained_contracts(tmp_path: Path) -> None:
    contracts = create_api_app(tmp_path / "unused.db").state.authorization_contracts
    contracts = _retained_before_enterprise(contracts)
    retained = tuple(item for item in contracts if not item.path.startswith(MONETARY_M7_PREFIXES))
    assert len(retained) == 620
    assert authorization_inventory_digest(retained) == "9ef5a1c3f1289de6e1a85fbbaa42b784e1dfe95f17cec3c6ad060c7f67830dfe"
    by_key = {(item.method, item.path): item for item in contracts}
    monetary = tuple(item for item in contracts if item.path.startswith(MONETARY_M7_PREFIXES))
    assert len(monetary) == 31
    assert sum(item.path.startswith("/api/v2/stock-sales/") for item in monetary) == 22
    assert all(item.mode == "all" for item in monetary)
    valuation = {
        (method, "/api/v2/stock-sales/orders/{identifier}" + suffix): operation
        for method, suffix, operation in (
            ("POST", "/valuations", "prepare"), ("POST", "/valuation-reversals", "prepare_reversal"),
            ("GET", "/fx-plans/{plan_id}", "read"), ("POST", "/fx-plans/{plan_id}/review", "review"),
            ("POST", "/fx-plans/{plan_id}/post", "post"),
        )
    }
    from reconforge.infrastructure.postgres_monetary_stock_sales import VALUATION_PERMISSIONS
    assert authorization_inventory_digest(tuple(item for item in contracts if (item.method, item.path) not in valuation)) == "a5a57e3066c068c0c7f2ad45a1b0fdf58ca5eb020be234fbc0ca9a5cf25622c9"
    additions = {
        "/api/v2/stock-sales/orders/{identifier}/collection/prepare": "receivables.manage",
        "/api/v2/stock-sales/orders/{identifier}/collection/review": "receivables.approve",
    }
    for item in monetary:
        if (item.method, item.path) in valuation:
            assert set(item.permissions) == set(VALUATION_PERMISSIONS[valuation[item.method, item.path]])
            continue
        old_path = "/api/v1" + item.path[len("/api/v2" if item.path.startswith("/api/v2/") else "/api/v3"):]
        old = by_key[item.method, old_path]
        expected = set(old.permissions) | ({additions[item.path]} if item.path in additions else set())
        assert set(item.permissions) == expected
    assert not any(item.path.startswith("/api/v2/stock-sales/commerce/") for item in contracts)


def test_wave3_routes_require_exact_authority_and_preserve_all_accepted_route_contracts(tmp_path: Path) -> None:
    """Bind the three added dependencies without weakening the retained 429 routes."""
    contracts = tuple(contract for contract in create_api_app(tmp_path / "unused.db").state.authorization_contracts
                      if not contract.path.startswith(WAVE4_PREFIXES + WAVE5_PREFIXES))
    contracts = _retained_before_enterprise(contracts)
    expected = (
        RouteAuthorizationContract(
            "GET", "/api/v1/fixed-assets/plans/{plan_id}/evidence", "all", ("finance_core.read",),
        ),
        RouteAuthorizationContract(
            "POST", "/api/v1/commercial-collections/plans/{plan_id}/cancel", "all",
            ("finance_core.validate", "receivables.manage", "sales.approve"),
        ),
        RouteAuthorizationContract(
            "POST", "/api/v1/landed-cost/plans/{identifier}/cancel", "all",
            ("finance_core.read", "finance_core.validate", "inventory.post", "inventory.read",
             "inventory.valuation.approve", "payables.approve", "payables.read", "payables.settle"),
        ),
    )
    added_keys = {(contract.method, contract.path) for contract in expected}
    actual_added = tuple(contract for contract in contracts if (contract.method, contract.path) in added_keys)
    assert actual_added == expected
    retained = tuple(contract for contract in contracts if (contract.method, contract.path) not in added_keys
                     and not contract.path.startswith(ENTERPRISE_M1_PREFIXES + ENTERPRISE_M2_PREFIXES + ENTERPRISE_M3_PREFIXES + ENTERPRISE_M4_PREFIXES + ENTERPRISE_M7_PREFIXES))
    assert len(retained) == 429
    assert authorization_inventory_digest(retained) == "1c1581c2a7d8baf52e80253d5c5e8d026f09de431b250efdb4c89ea1bfd4232d"
    validate_authorization_surface(create_api_app(tmp_path / "complete.db").state.authorization_contracts,
                                   require_critical_routes=True)


def test_wave4_source_routes_preserve_accepted_authority_and_require_exact_permissions(tmp_path: Path) -> None:
    contracts = create_api_app(tmp_path / "unused.db").state.authorization_contracts
    contracts = _retained_before_enterprise(contracts)
    retained = tuple(contract for contract in contracts if not contract.path.startswith(WAVE4_PREFIXES + WAVE5_PREFIXES + ENTERPRISE_M1_PREFIXES + ENTERPRISE_M2_PREFIXES + ENTERPRISE_M3_PREFIXES + ENTERPRISE_M4_PREFIXES + ENTERPRISE_M7_PREFIXES))
    assert len(retained) == 432
    assert authorization_inventory_digest(retained) == "1444692a691300fa3bd63fef6ab70f1c02d195a0b1b9b15b7673b58c847beb76"
    read = ("finance_core.read", "inventory.read", "receivables.read", "sales.read")
    prepare = ("finance_core.manage", "finance_core.read", "finance_core.reverse", "inventory.read",
               "inventory.valuation.manage", "receivables.manage", "receivables.read", "sales.manage", "sales.read")
    expected = [RouteAuthorizationContract("GET", "/api/v1/customer-returns/" + path, "all", read)
                for path in ("plans", "plans/{plan_id}", "plans/{plan_id}/balance")]
    expected += [RouteAuthorizationContract("POST", "/api/v1/customer-returns/" + path, "all", prepare)
                 for path in ("plans", "plans/{return_id}/refunds")]
    expected += [RouteAuthorizationContract("POST", "/api/v1/customer-returns/plans/{plan_id}/" + action, "all", permissions)
                 for action, permissions in (
                     ("cancel", ("finance_core.read", "finance_core.validate", "inventory.read", "receivables.read", "sales.approve", "sales.read")),
                     ("post", ("finance_core.post", "finance_core.read", "finance_core.reverse", "inventory.post", "inventory.read",
                               "inventory.valuation.approve", "receivables.manage", "receivables.read", "sales.manage", "sales.read")),
                     ("review", ("finance_core.read", "finance_core.reverse", "finance_core.validate", "inventory.read",
                                 "inventory.valuation.approve", "receivables.read", "sales.approve", "sales.read")),
                 )]
    expected += [RouteAuthorizationContract("GET", "/api/v1/operational-fx-tax/" + path, "all", ("finance_core.read",))
                 for path in ("invoices", "invoices/{source_id}", "plans/{plan_id}/evidence")]
    expected += [RouteAuthorizationContract("POST", "/api/v1/operational-fx-tax/" + path, "all", (permission,))
                 for path, permission in (("invoices", "finance_core.manage"), ("invoices/{source_id}/settlements", "finance_core.manage"),
                                          ("invoices/{source_id}/revaluations", "finance_core.manage"),
                                          ("invoices/{source_id}/revaluation-reversals", "finance_core.manage"),
                                          ("plans/{plan_id}/post", "finance_core.post"), ("plans/{plan_id}/review", "finance_core.validate"))]
    expected += [RouteAuthorizationContract(method, "/api/v1/procurement-commitments/" + path, "all", permissions)
                 for method, path, permissions in (
                     ("GET", "orders/{order_id}", ("budget_control.read", "finance_core.read", "inventory.read", "payables.read")),
                     ("POST", "orders", ("budget_control.manage", "budget_control.read", "finance_core.read", "inventory.read", "payables.manage", "payables.read")),
                     ("POST", "orders/{order_id}/consume", ("budget_control.manage", "budget_control.read", "finance_core.post", "finance_core.read", "inventory.read", "payables.approve", "payables.read")),
                     ("POST", "orders/{order_id}/release", ("budget_control.manage", "budget_control.read", "finance_core.read", "inventory.read", "payables.approve", "payables.read")),
                 )]
    supplier_read = ("finance_core.read", "inventory.read", "payables.read")
    expected += [RouteAuthorizationContract("GET", "/api/v1/supplier-returns/" + path, "all", supplier_read)
                 for path in ("plans/{plan_id}", "orders/{order_id}")]
    expected += [RouteAuthorizationContract("POST", "/api/v1/supplier-returns/" + path, "all", permissions)
                 for path, permissions in (
                     ("plans", ("finance_core.manage", "finance_core.read", "finance_core.reverse", "inventory.manage", "inventory.read",
                                "inventory.valuation.manage", "inventory.valuation.reverse.manage", "payables.manage", "payables.read")),
                     ("plans/{plan_id}/review", ("finance_core.read", "finance_core.reverse", "finance_core.validate", "inventory.post", "inventory.read",
                                               "inventory.valuation.approve", "inventory.valuation.reverse.approve", "payables.approve", "payables.read")),
                     ("plans/{plan_id}/post", ("finance_core.post", "finance_core.read", "finance_core.reverse", "inventory.post", "inventory.read",
                                             "inventory.valuation.approve", "inventory.valuation.reverse.approve", "payables.manage", "payables.read")),
                     ("plans/{plan_id}/cancel", ("finance_core.read", "finance_core.validate", "inventory.read",
                                               "inventory.valuation.reverse.approve", "payables.approve", "payables.read")),
                 )]
    added = [contract for contract in contracts if contract.path.startswith(WAVE4_PREFIXES)]
    assert sorted(added, key=lambda item: (item.method, item.path)) == sorted(expected, key=lambda item: (item.method, item.path))


def test_mutating_route_modules_declare_a_server_boundary_or_explicit_protocol_classification() -> None:
    """Prevent a new mutating API module from silently bypassing E-1005 scope review."""

    violations: list[str] = []
    for path in sorted(ROUTES_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        has_mutation = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"post", "put", "patch", "delete"}
            for node in ast.walk(tree)
        )
        if not has_mutation or path.name in SPECIAL_ROUTE_MODULES:
            continue
        source = path.read_text(encoding="utf-8")
        reviewed_helpers = HANDLER_BOUNDARY_HELPERS.get(path.name, frozenset())
        calls = {
            node.func.id for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        if not any(marker in source for marker in SERVER_BOUNDARY_MARKERS) and not calls & reviewed_helpers:
            violations.append(path.name)

    assert violations == [], (
        "Mutating route modules must either call/declare a server scope or be "
        f"added to the reviewed protocol allowlist: {violations}"
    )


@pytest.mark.parametrize("method,path,required", [
    ("POST", "/api/v1/people-project-payroll/employees", "people_project_payroll.read_sensitive"),
    ("POST", "/api/v1/people-project-payroll/payruns", "budget_control.manage"),
    ("POST", "/api/v1/people-project-payroll/plans/{plan_id}/post", "finance_core.post"),
    ("POST", "/api/v1/intercompany-fx/sources/{source_id}/revaluation-reversals", "finance_core.reverse"),
    ("POST", "/api/v1/intercompany-fx/sources/{source_id}/settlements", "finance_core.manage"),
    ("POST", "/api/v1/accrual-deferral/sources/{source_id}/reversals", "finance_core.reverse"),
    ("POST", "/api/v1/accrual-deferral/plans/{plan_id}/post", "accrual_deferral.post"),
    ("GET", "/api/v1/accrual-deferral/plans/{plan_id}/evidence/export", "finance_core.read"),
    ("POST", "/api/v1/project-time-billing/plans/{plan_id}/post", "receivables.approve"),
    ("GET", "/api/v1/project-time-billing/plans/{plan_id}", "people_project_payroll.read"),
    ("GET", "/api/v1/project-time-billing/catalog", "receivables.read"),
    ("GET", "/api/v1/intercompany-source-cashflow/sources/{source_id}", "finance_core.read"),
    ("GET", "/api/v1/intercompany-source-cashflow/sources/{source_id}/evidence/export", "intercompany_fx.read"),
    ("GET", "/api/v1/intercompany-group-diagnostic/report", "finance_core.read"),
    ("GET", "/api/v1/intercompany-group-diagnostic/evidence", "intercompany_fx.read"),
    ("GET", "/api/v1/project-source-reconciliation/report", "people_project_payroll.read"),
    ("GET", "/api/v1/project-source-reconciliation/evidence", "receivables.read"),
    ("GET", "/api/v1/project-source-reconciliation/close-diagnostics", "people_project_payroll.read"),
    ("GET", "/api/v1/project-source-reconciliation/close-diagnostics/evidence", "receivables.read"),
    ("GET", "/api/v1/intercompany-fx/sources/{source_id}/native-evidence-bundle", "intercompany_fx.read"),
    ("GET", "/api/v1/intercompany-fx/sources/{source_id}/native-evidence-bundle", "finance_core.read"),
    ("POST", "/api/v2/stock-sales/orders/{identifier}/collection/prepare", "receivables.manage"),
    ("POST", "/api/v2/stock-sales/orders/{identifier}/collection/review", "receivables.approve"),
    ("POST", "/api/v3/customer-partial-returns/plans/{plan_id}/post", "finance_core.post"),
    ("POST", "/api/v3/customer-partial-returns/plans/{original_id}/reversals", "finance_core.reverse"),
    ("POST", "/api/v2/stock-sales/orders/{identifier}/valuations", "receivables.manage"),
    ("POST", "/api/v2/stock-sales/orders/{identifier}/valuation-reversals", "finance_core.reverse"),
    ("POST", "/api/v2/stock-sales/orders/{identifier}/fx-plans/{plan_id}/review", "receivables.approve"),
    ("POST", "/api/v2/stock-sales/orders/{identifier}/fx-plans/{plan_id}/post", "finance_core.post"),
])
def test_enterprise_sensitive_contract_refuses_adjacent_authority(
    tmp_path: Path, method: str, path: str, required: str,
) -> None:
    from dataclasses import replace

    contracts = create_api_app(tmp_path / "unused.db").state.authorization_contracts
    contracts = _retained_before_enterprise(contracts)
    changed = tuple(replace(item, permissions=tuple(permission for permission in item.permissions if permission != required))
                    if (item.method, item.path) == (method, path) else item for item in contracts)
    assert changed != contracts
    with pytest.raises(ValueError, match="Critical.*contract"):
        validate_authorization_surface(changed, require_critical_routes=True)


def test_wave5_additions_preserve_every_accepted_wave4_route(tmp_path: Path) -> None:
    contracts = create_api_app(tmp_path / "unused.db").state.authorization_contracts
    contracts = _retained_before_enterprise(contracts)
    retained = tuple(contract for contract in contracts if not contract.path.startswith(WAVE5_PREFIXES + ENTERPRISE_M1_PREFIXES + ENTERPRISE_M2_PREFIXES + ENTERPRISE_M3_PREFIXES + ENTERPRISE_M4_PREFIXES + ENTERPRISE_M7_PREFIXES))
    assert len(retained) == 459
    assert authorization_inventory_digest(retained) == "f41b3007bbcc9cc1285cc836be0cb2e81d2e2c4e03713f83f6d245db27fccc9a"


def test_each_mutating_route_handler_reaches_a_reviewed_server_boundary() -> None:
    """Prevent a new handler from relying only on a neighboring route's guard."""

    violations: list[str] = []
    for path in sorted(ROUTES_ROOT.glob("*.py")):
        if path.name in SPECIAL_ROUTE_MODULES:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        reviewed_helpers = HANDLER_BOUNDARY_HELPERS.get(path.name, frozenset())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            is_mutating_handler = any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr in {"post", "put", "patch", "delete"}
                for decorator in node.decorator_list
            )
            if not is_mutating_handler:
                continue
            handler_source = ast.get_source_segment(source, node) or ""
            handler_calls = {
                call.func.id
                for call in ast.walk(node)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            }
            has_direct_boundary = any(marker in handler_source for marker in SERVER_BOUNDARY_MARKERS)
            has_reviewed_helper = bool(handler_calls & reviewed_helpers)
            if not has_direct_boundary and not has_reviewed_helper:
                violations.append(f"{path.name}:{node.name}")

    assert violations == [], (
        "Every mutating handler must reach a direct server boundary or a "
        "reviewed module helper: "
        f"{violations}"
    )


def test_inventory_rejects_unclassified_and_stale_allowlisted_routes() -> None:
    router = APIRouter(prefix="/unsafe")

    @router.get("")
    def unsafe() -> dict[str, bool]:
        return {"ok": False}

    with pytest.raises(ValueError, match="lacks an authorization contract"):
        build_route_authorization_inventory(
            (router,), prefix="/api/v1", identity_routes=frozenset(), public_routes=frozenset()
        )
    with pytest.raises(ValueError, match="not registered"):
        build_route_authorization_inventory(
            (router,), prefix="/api/v1", identity_routes=frozenset(),
            public_routes=frozenset({("GET", "/api/v1/unsafe"), ("GET", "/api/v1/missing")}),
        )


def test_permission_dependencies_freeze_and_validate_their_contract() -> None:
    mutable = {"evidence.read"}
    dependency = require_any_permission(mutable)
    mutable.add("admin")
    assert dependency.__reconforge_permissions__ == frozenset({"evidence.read"})  # type: ignore[attr-defined]
    assert require_permission("audit.read").__reconforge_permission_mode__ == "all"  # type: ignore[attr-defined]
    for invalid in (set(), {""}, {"ADMIN"}, {"permission with spaces"}):
        with pytest.raises(ValueError, match="valid non-empty"):
            require_any_permission(invalid)


def test_mutating_authorization_surface_fails_closed_outside_explicit_handshakes() -> None:
    with pytest.raises(ValueError, match="publicly authorized"):
        validate_authorization_surface(
            (RouteAuthorizationContract("POST", "/api/v1/finance/post", "public"),)
        )
    with pytest.raises(ValueError, match="identity-only authorization"):
        validate_authorization_surface(
            (RouteAuthorizationContract("DELETE", "/api/v1/users/{id}", "identity"),)
        )
    with pytest.raises(ValueError, match="permission contract"):
        validate_authorization_surface(
            (RouteAuthorizationContract("PATCH", "/api/v1/finance/post", "all"),)
        )
    validate_authorization_surface(
        (
            RouteAuthorizationContract("POST", "/api/v1/auth/login", "public"),
            RouteAuthorizationContract("POST", "/scim/v2/Users", "scim"),
            RouteAuthorizationContract("POST", "/api/v1/finance/post", "all", ("finance.post",)),
            RouteAuthorizationContract("POST", "/api/v1/workflow/objects/{object_type}/{object_id}/transition", "dynamic"),
        )
    )


def test_critical_financial_route_permission_contract_cannot_drift() -> None:
    with pytest.raises(ValueError, match="Critical API route authorization contract drifted"):
        validate_authorization_surface(
            (
                RouteAuthorizationContract(
                    "POST",
                    "/api/v1/finance-core/entries/{entry_id}/validate",
                    "all",
                    ("finance_core.manage",),
                ),
            )
        )


@pytest.mark.parametrize("route,permissions", [
    ("/api/v1/inventory-transfer/transfers/{identifier}/review", ("inventory_transfer.approve", "inventory.manage")),
    ("/api/v1/inventory-transfer/transfers/{identifier}/post", ("inventory_transfer.post", "inventory.post")),
    ("/api/v1/sales-revenue/documents/{identifier}/invoice/review", ("sales.manage", "finance_core.validate")),
    ("/api/v1/procurement-operations/cycles/{cycle_id}/commands/receive", ("payables.manage", "finance_core.post")),
    ("/api/v1/procurement-operations/cycles/{cycle_id}/commands/pay", ("finance_core.post",)),
])
def test_erp_financial_actions_refuse_adjacent_authority(route: str, permissions: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="Critical API route authorization contract drifted"):
        validate_authorization_surface((RouteAuthorizationContract("POST", route, "all", tuple(sorted(permissions))),))
