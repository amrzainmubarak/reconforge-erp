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
