"""Health and version routes for local and PostgreSQL server profiles."""

from __future__ import annotations

from fastapi import APIRouter, Request

from reconforge import __version__
from reconforge.api.dependencies import get_db_path
from reconforge.api.errors import APIError
from reconforge.api.server_identity import get_postgres_identity_factory, server_identity_enabled
from reconforge.db import DatabaseError, database_status
from reconforge.db.migrations import MIGRATIONS
from reconforge.infrastructure.postgres_operations import (
    PostgresMigrationStatusProvider,
    PostgresOperationsError,
)

router = APIRouter()


@router.get("/health")
def health(request: Request) -> dict[str, object]:
    """Return backend-aware health without exposing secrets or environment data."""

    if server_identity_enabled(request):
        return _server_health(request)

    try:
        db_path = get_db_path(request)
    except APIError:
        db_path = None
    database_reachable = False
    schema_version = 0
    try:
        if db_path is None:
            raise DatabaseError("Tenant selection is required.")
        status = database_status(db_path)
        database_reachable = True
        schema_version = status.current_version
    except DatabaseError:
        database_reachable = False
    return {
        "status": "ok" if database_reachable else "degraded",
        "service": "reconforge-local-api",
        "version": __version__,
        "database": {
            "reachable": database_reachable,
            "schema_version": schema_version,
            "latest_schema_version": MIGRATIONS[-1].version,
            "path_summary": getattr(db_path, "name", "tenant database"),
        },
    }


def _server_health(request: Request) -> dict[str, object]:
    """Return PostgreSQL reachability and migration readiness for Server Profile."""

    factory = get_postgres_identity_factory(request)
    migration_status = None
    try:
        if factory is None:
            raise PostgresOperationsError("PostgreSQL server factory is not configured.")
        migration_status = PostgresMigrationStatusProvider(factory)("postgresql-server")
    except Exception:
        # Health is intentionally non-diagnostic: connection strings, driver
        # errors, and database messages must not cross this unauthenticated
        # boundary. A failed probe is reported as degraded instead.
        migration_status = None

    reachable = migration_status is not None
    pending_migrations = len(migration_status.pending_versions) if migration_status is not None else None
    ready = reachable and pending_migrations == 0
    return {
        "status": "ok" if ready else "degraded",
        "service": "reconforge-server-api",
        "version": __version__,
        "database": {
            "backend": "postgresql",
            "reachable": reachable,
            "schema_version": migration_status.current_version if migration_status is not None else None,
            "latest_schema_version": migration_status.latest_version if migration_status is not None else None,
            "pending_migrations": pending_migrations,
            "path_summary": "server-managed",
        },
    }


@router.get("/version")
def version() -> dict[str, str]:
    """Return package and API version metadata."""

    return {
        "package": "reconforge-erp",
        "version": __version__,
        "api_version": "v1",
        "scope": "local/self-hosted foundation",
    }
