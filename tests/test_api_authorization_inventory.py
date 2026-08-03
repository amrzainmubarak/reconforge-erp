from __future__ import annotations

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

EXPECTED_ROUTE_COUNT = 207
EXPECTED_DIGEST = "cd3726635977c39e303d83ef53281bb50b1048a0c5f46cd9e515916e509cf3bf"


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
    validate_authorization_surface(contracts)


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
