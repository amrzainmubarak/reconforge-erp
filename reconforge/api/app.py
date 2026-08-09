"""FastAPI app factory for the local REST API foundation."""

from __future__ import annotations

import re
import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from threading import Lock
from time import monotonic_ns
from typing import Final, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from reconforge import __version__
from reconforge.api.authorization import (
    authorization_inventory_digest,
    build_route_authorization_inventory,
    validate_authorization_surface,
)
from reconforge.api.browser_session import BROWSER_SESSION_COOKIE
from reconforge.api.errors import (
    APIError,
    api_error_handler,
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from reconforge.api.routes import (
    access_administration,
    accounts,
    audit,
    audit_administration,
    auth,
    close,
    connectors,
    consolidation_close,
    consolidation_deferred_tax,
    consolidation_impairment,
    consolidation_intercompany,
    consolidation_ownership,
    consolidation_ppa,
    emergency_access,
    evidence,
    exceptions,
    finance_core,
    health,
    identity_administration,
    inventory_core,
    inventory_planning,
    inventory_valuation,
    inventory_valuation_reversal,
    master_data,
    metrics,
    payables,
    professional_invoice_payment,
    receivables,
    reconciliation,
    retail_settlement,
    roles,
    scim,
    scope_grants,
    scoped_exports,
    security_center,
    security_governance,
    users,
    webauthn,
    workflow,
)
from reconforge.api.scim_security import SCIMHTTPError, scim_error_handler
from reconforge.api.server_identity import (
    authenticate_server_request,
    server_identity_enabled,
    server_principal_from_authentication,
)
from reconforge.application.pagination import CursorCodec
from reconforge.auth.federation import FederationProvider, FederationVerifier
from reconforge.auth.policy_cache import PolicyDecisionCache
from reconforge.auth.webauthn_config import WebAuthnRuntime
from reconforge.db import resolve_db_path
from reconforge.db.tenancy import TenantDatabaseRouter
from reconforge.infrastructure.postgres import (
    PostgresPooledConnectionFactory,
    PostgresSettings,
)
from reconforge.infrastructure.redis import (
    RedisConnectionFactory,
    RedisPolicyCacheVersionStore,
    RedisSettings,
    TenantRedisStore,
)
from reconforge.observability import ObservabilityRuntime, safe_attributes, telemetry_request_context
from reconforge.platform.common import ServerPrincipal, server_principal_context, trusted_local_mode
from reconforge.reliability_sources import HttpReliabilityWindow

ExceptionHandler = Callable[[Request, Exception], Response | Awaitable[Response]]

SECURITY_RESPONSE_HEADERS: Final[dict[str, str]] = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "accelerometer=(), ambient-light-sensor=(), battery=(), camera=(), geolocation=(), microphone=(), payment=(), usb=()",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-Permitted-Cross-Domain-Policies": "none",
    "X-XSS-Protection": "0",
}
CONTENT_SECURITY_POLICY: Final[str] = (
    "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
    "form-action 'self'; script-src 'self'; style-src 'self'; style-src-elem 'self'; "
    "style-src-attr 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
    "connect-src 'self'; manifest-src 'self'; worker-src 'self'; upgrade-insecure-requests"
)


class SPAStaticFiles(StaticFiles):
    """Serve one built SPA without turning missing asset paths into HTML."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            method = str(scope.get("method", "")).upper()
            leaf = path.rsplit("/", 1)[-1]
            if exc.status_code != 404 or method not in {"GET", "HEAD"} or "." in leaf:
                raise
            return await super().get_response("index.html", scope)


def create_api_app(
    db_path: Path | str,
    *,
    tenant_db_root: Path | str | None = None,
    redis_url: str | None = None,
    redis_require_tls: bool = True,
    postgres_dsn: str | None = None,
    postgres_require_tls: bool = True,
    postgres_pool_size: int = 8,
    postgres_pool_acquire_timeout_seconds: float = 30.0,
    cursor_signing_key: bytes | None = None,
    observability: ObservabilityRuntime | None = None,
    reliability_window: HttpReliabilityWindow | None = None,
    federation_providers: Mapping[str, FederationProvider] | None = None,
    federation_verifiers: Mapping[str, FederationVerifier] | None = None,
    federation_air_gap_mode: bool = False,
    webauthn_runtime: WebAuthnRuntime | None = None,
    web_root: Path | str | None = None,
    allowed_hosts: tuple[str, ...] = (),
    secure_transport: bool = False,
    policy_cache_enabled: bool = False,
) -> FastAPI:
    """Create the API with local mode or an explicit server identity profile."""

    resolved_db_path = resolve_db_path(db_path)
    resolved_web_root = Path(web_root).resolve() if web_root is not None else None
    if resolved_web_root is not None and not (resolved_web_root.is_dir() and (resolved_web_root / "index.html").is_file()):
        raise ValueError("web_root must contain a built index.html file.")
    normalized_hosts = tuple(dict.fromkeys(host.strip().casefold() for host in allowed_hosts if host.strip()))
    if any(
        ".." in host or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host)
        for host in normalized_hosts
    ):
        raise ValueError("allowed_hosts must contain exact DNS names or IPv4 addresses only.")
    if postgres_dsn is not None and tenant_db_root is None:
        raise ValueError("tenant_db_root is required when PostgreSQL server identity is enabled.")
    app = FastAPI(
        title="ReconForge Local REST API",
        version=__version__,
        description="Local/self-hosted REST API foundation for ReconForge DB-backed workflows.",
    )
    app.state.db_path = resolved_db_path
    app.state.tenant_db_router = TenantDatabaseRouter.from_root(tenant_db_root) if tenant_db_root is not None else None
    app.state.postgres_identity_factory = None
    if postgres_dsn is not None:
        app.state.postgres_identity_factory = PostgresPooledConnectionFactory(
            PostgresSettings(dsn=postgres_dsn, require_tls=postgres_require_tls),
            max_size=postgres_pool_size,
            acquire_timeout_seconds=postgres_pool_acquire_timeout_seconds,
        )
        app.router.add_event_handler("shutdown", app.state.postgres_identity_factory.close)
    # The bounded PostgreSQL ledger uses the same secured connection factory
    # as server identity, but remains an explicit API capability boundary.
    app.state.postgres_ledger_factory = app.state.postgres_identity_factory
    app.state.postgres_finance_core_factory = app.state.postgres_identity_factory
    app.state.postgres_master_data_factory = app.state.postgres_identity_factory
    app.state.postgres_close_factory = app.state.postgres_identity_factory
    app.state.postgres_consolidation_close_factory = app.state.postgres_identity_factory
    app.state.postgres_consolidation_ownership_factory = app.state.postgres_identity_factory
    app.state.postgres_ppa_factory = app.state.postgres_identity_factory
    app.state.postgres_deferred_tax_factory = app.state.postgres_identity_factory
    app.state.postgres_consolidation_impairment_factory = app.state.postgres_identity_factory
    app.state.postgres_consolidation_intercompany_factory = app.state.postgres_identity_factory
    app.state.postgres_evidence_factory = app.state.postgres_identity_factory
    app.state.postgres_scoped_exports_factory = app.state.postgres_identity_factory
    app.state.postgres_reconciliation_factory = app.state.postgres_identity_factory
    app.state.postgres_writeback_factory = app.state.postgres_identity_factory
    app.state.postgres_retail_settlement_factory = app.state.postgres_identity_factory
    app.state.postgres_professional_invoice_payment_factory = app.state.postgres_identity_factory
    app.state.federation_providers = dict(federation_providers or {})
    app.state.federation_verifiers = dict(federation_verifiers or {})
    app.state.federation_air_gap_mode = federation_air_gap_mode
    app.state.webauthn_runtime = webauthn_runtime
    app.state.cursor_codec = CursorCodec(cursor_signing_key) if cursor_signing_key is not None else None
    app.state.observability = observability or ObservabilityRuntime.disabled()
    app.state.reliability_window = reliability_window
    redis_factory: RedisConnectionFactory | None = None
    if redis_url is not None:
        redis_factory = RedisConnectionFactory(RedisSettings(url=redis_url, require_tls=redis_require_tls))
        app.state.redis_store = TenantRedisStore(redis_factory)
        app.router.add_event_handler("shutdown", redis_factory.close)
    else:
        app.state.redis_store = None
    app.state.login_failures = defaultdict(deque)
    app.state.login_failures_lock = Lock()
    app.state.web_root = resolved_web_root
    app.state.secure_transport = secure_transport
    app.state.allowed_hosts = normalized_hosts
    # Explicit opt-in only: the middleware below invalidates after every
    # mutation, so callers do not inherit an invisible freshness dependency.
    # When Redis is configured, a shared generation makes that invalidation
    # visible to other API processes without storing policy decisions there.
    policy_version_store = (
        RedisPolicyCacheVersionStore(redis_factory)
        if policy_cache_enabled and redis_factory is not None
        else None
    )
    app.state.policy_cache_version_store = policy_version_store
    app.state.policy_decision_cache = (
        PolicyDecisionCache(version_store=policy_version_store) if policy_cache_enabled else None
    )
    if normalized_hosts:
        # Register before decorator middleware so request IDs and the response
        # policy still wrap a Host rejection.
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(normalized_hosts))

    @app.middleware("http")
    async def observe_request(request: Request, call_next: RequestResponseEndpoint) -> Response:
        runtime: ObservabilityRuntime = request.app.state.observability
        started = monotonic_ns()
        method = request.method.upper()
        with runtime.span("HTTP request", {"http.request.method": method}) as span:
            try:
                response = await call_next(request)
            except Exception as exc:
                window: HttpReliabilityWindow | None = request.app.state.reliability_window
                if window is not None:
                    window.record(status_code=500, duration_ms=max(0, (monotonic_ns() - started) // 1_000_000))
                if span is not None:
                    span.set_attribute("error.type", type(exc).__name__)
                raise
            cache = getattr(request.app.state, "policy_decision_cache", None)
            if cache is not None and method not in {"GET", "HEAD", "OPTIONS", "TRACE"}:
                cache.invalidate()
            route = request.scope.get("route")
            local_template = str(getattr(route, "path", ""))
            candidate = local_template if local_template.startswith("/scim/v2") else "/api/v1" + local_template
            known_routes = {(contract.method, contract.path) for contract in request.app.state.authorization_contracts}
            route_template = candidate if (method, candidate) in known_routes else "unmatched"
            attributes = safe_attributes(
                {
                    "http.request.method": method,
                    "http.response.status_code": response.status_code,
                    "http.route": route_template,
                }
            )
            if span is not None:
                for key, value in attributes.items():
                    span.set_attribute(key, value)
            duration_ms = max(0, (monotonic_ns() - started) // 1_000_000)
            runtime.record_request(duration_ms=duration_ms, attributes=attributes)
            window = request.app.state.reliability_window
            if window is not None:
                window.record(status_code=response.status_code, duration_ms=duration_ms)
            return response

    @app.middleware("http")
    async def add_request_id(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        principal: ServerPrincipal | None = None
        if (
            server_identity_enabled(request)
            and not request.url.path.startswith("/scim/v2")
            and request.url.path
            not in {
                "/api/v1/health",
                "/api/v1/version",
                "/api/v1/auth/login",
                "/api/v1/auth/browser/login",
                "/api/v1/auth/federation/challenge",
                "/api/v1/auth/federated-login",
            }
        ):
            authorization = request.headers.get("authorization", "")
            scheme, separator, bearer_credential = authorization.partition(" ")
            presented_credential: str | None = None
            transport = ""
            if separator and scheme.casefold() == "bearer" and bearer_credential.strip():
                presented_credential = bearer_credential.strip()
                transport = "bearer"
            elif request.cookies.get(BROWSER_SESSION_COOKIE, ""):
                presented_credential = request.cookies[BROWSER_SESSION_COOKIE]
                transport = "browser_cookie"
            if presented_credential:
                authenticated = await run_in_threadpool(
                    authenticate_server_request, request, presented_credential
                )
                if authenticated is not None:
                    principal = server_principal_from_authentication(authenticated)
                    request.state.server_principal = principal
                    request.state.reconforge_auth_transport = transport
        with telemetry_request_context(request.state.request_id), trusted_local_mode(False):
            if principal is None:
                response = await call_next(request)
            else:
                with server_principal_context(principal):
                    response = await call_next(request)
        response.headers["x-request-id"] = request.state.request_id
        return response

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_RESPONSE_HEADERS.items():
            response.headers.setdefault(header, value)
        response.headers.setdefault("Server", "reconforge-api")
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        if request.app.state.secure_transport:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    app.add_exception_handler(APIError, cast(ExceptionHandler, api_error_handler))
    app.add_exception_handler(SCIMHTTPError, cast(ExceptionHandler, scim_error_handler))
    app.add_exception_handler(StarletteHTTPException, cast(ExceptionHandler, http_error_handler))
    app.add_exception_handler(RequestValidationError, cast(ExceptionHandler, validation_error_handler))
    app.add_exception_handler(Exception, unhandled_error_handler)

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(emergency_access.router, prefix="/api/v1")
    app.include_router(webauthn.router, prefix="/api/v1")
    app.include_router(users.router, prefix="/api/v1")
    app.include_router(roles.router, prefix="/api/v1")
    app.include_router(scope_grants.router, prefix="/api/v1")
    app.include_router(security_center.router, prefix="/api/v1")
    app.include_router(security_governance.router, prefix="/api/v1")
    app.include_router(identity_administration.router, prefix="/api/v1")
    app.include_router(access_administration.router, prefix="/api/v1")
    app.include_router(audit.router, prefix="/api/v1")
    app.include_router(audit_administration.router, prefix="/api/v1")
    app.include_router(workflow.router, prefix="/api/v1")
    if resolved_web_root is not None:
        app.mount("/", SPAStaticFiles(directory=resolved_web_root, html=True), name="studio-web")
    app.include_router(accounts.router, prefix="/api/v1")
    app.include_router(close.router, prefix="/api/v1")
    app.include_router(consolidation_close.router, prefix="/api/v1")
    app.include_router(consolidation_ownership.router, prefix="/api/v1")
    app.include_router(consolidation_ppa.router, prefix="/api/v1")
    app.include_router(consolidation_deferred_tax.router, prefix="/api/v1")
    app.include_router(consolidation_impairment.router, prefix="/api/v1")
    app.include_router(consolidation_intercompany.router, prefix="/api/v1")
    app.include_router(connectors.router, prefix="/api/v1")
    app.include_router(evidence.router, prefix="/api/v1")
    app.include_router(scoped_exports.router, prefix="/api/v1")
    app.include_router(reconciliation.router, prefix="/api/v1")
    app.include_router(retail_settlement.router, prefix="/api/v1")
    app.include_router(professional_invoice_payment.router, prefix="/api/v1")
    app.include_router(exceptions.router, prefix="/api/v1")
    app.include_router(metrics.router, prefix="/api/v1")
    app.include_router(payables.router, prefix="/api/v1")
    app.include_router(receivables.router, prefix="/api/v1")
    app.include_router(master_data.router, prefix="/api/v1")
    app.include_router(finance_core.router, prefix="/api/v1")
    app.include_router(inventory_core.router, prefix="/api/v1")
    app.include_router(inventory_planning.router, prefix="/api/v1")
    app.include_router(inventory_valuation.router, prefix="/api/v1")
    app.include_router(inventory_valuation_reversal.router, prefix="/api/v1")
    app.include_router(scim.router)
    authorization_routers = (
        health.router,
        auth.router,
        emergency_access.router,
        webauthn.router,
        users.router,
        roles.router,
        security_center.router,
        security_governance.router,
        identity_administration.router,
        access_administration.router,
        audit.router,
        audit_administration.router,
        workflow.router,
        accounts.router,
        close.router,
        consolidation_close.router,
        consolidation_ownership.router,
        evidence.router,
        scoped_exports.router,
        consolidation_ppa.router,
        consolidation_deferred_tax.router,
        consolidation_impairment.router,
        consolidation_intercompany.router,
        connectors.router,
        reconciliation.router,
        retail_settlement.router,
        professional_invoice_payment.router,
        exceptions.router,
        metrics.router,
        payables.router,
        receivables.router,
        master_data.router,
        finance_core.router,
        inventory_core.router,
        inventory_planning.router,
        inventory_valuation.router,
        inventory_valuation_reversal.router,
    )
    core_contracts = build_route_authorization_inventory(
        authorization_routers,
        prefix="/api/v1",
        public_routes=frozenset(
            {
                ("GET", "/api/v1/health"),
                ("GET", "/api/v1/version"),
                ("POST", "/api/v1/auth/login"),
                ("POST", "/api/v1/auth/browser/login"),
                ("POST", "/api/v1/auth/federation/challenge"),
                ("POST", "/api/v1/auth/federated-login"),
            }
        ),
        identity_routes=frozenset(
            {
                ("POST", "/api/v1/auth/logout"),
                ("POST", "/api/v1/auth/step-up"),
                ("POST", "/api/v1/auth/emergency-access/requests"),
                ("GET", "/api/v1/auth/emergency-access/requests"),
                ("POST", "/api/v1/auth/emergency-access/requests/{access_id}/activate"),
                ("POST", "/api/v1/auth/emergency-access/requests/{access_id}/end"),
                ("POST", "/api/v1/auth/webauthn/registration/options"),
                ("POST", "/api/v1/auth/webauthn/registration/verify"),
                ("POST", "/api/v1/auth/webauthn/authentication/options"),
                ("POST", "/api/v1/auth/webauthn/authentication/verify"),
                ("GET", "/api/v1/auth/me"),
            }
        ),
    )
    scim_contracts = build_route_authorization_inventory(
        (scim.router,), prefix="", public_routes=frozenset(), identity_routes=frozenset()
    )
    app.state.authorization_contracts = tuple(sorted((*core_contracts, *scim_contracts)))
    validate_authorization_surface(app.state.authorization_contracts)
    app.state.authorization_contract_digest = authorization_inventory_digest(app.state.authorization_contracts)
    return app
