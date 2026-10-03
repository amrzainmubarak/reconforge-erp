from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import APIRouter

from reconforge.api import create_api_app
from reconforge.api.authorization import (
    RouteAuthorizationContract,
    build_route_authorization_inventory,
    validate_authorization_surface,
)
from reconforge.api.dependencies import require_any_permission, require_permission

EXPECTED_ROUTE_COUNT = 287
EXPECTED_DIGEST = "f6745d370dcb54e3162acf338a011a2504ac3057847fdefd4fa3d1050b7d99b9"
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
    "access_administration.py": frozenset({"_service"}),
    "accounts.py": frozenset({"_server_scope"}),
    "consolidation_deferred_tax.py": frozenset({"_enforce_server_policy"}),
    "consolidation_impairment.py": frozenset({"_enforce_server_policy"}),
    "consolidation_intercompany.py": frozenset({"_scope_for_payload", "_server_only"}),
    "consolidation_ownership_change.py": frozenset({"_enforce_server_policy"}),
    "consolidation_ppa.py": frozenset({"_enforce_server_policy"}),
    "emergency_access.py": frozenset({"_execute"}),
    "exceptions.py": frozenset({"_local_connection"}),
    "evidence.py": frozenset({"_enforce_server_evidence_permission"}),
    "finance_core.py": frozenset({"_server_finance_workspace"}),
    "finance_posting.py": frozenset({"_authority"}),
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

    assert len(contracts) == EXPECTED_ROUTE_COUNT
    assert app.state.authorization_contract_digest == EXPECTED_DIGEST
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
    validate_authorization_surface(contracts)


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
        if not any(marker in source for marker in SERVER_BOUNDARY_MARKERS):
            violations.append(path.name)

    assert violations == [], (
        "Mutating route modules must either call/declare a server scope or be "
        f"added to the reviewed protocol allowlist: {violations}"
    )


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
