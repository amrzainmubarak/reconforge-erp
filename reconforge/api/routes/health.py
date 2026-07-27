"""Health and version routes for the local API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from reconforge import __version__
from reconforge.api.dependencies import get_db_path
from reconforge.api.errors import APIError
from reconforge.db import DatabaseError, database_status
from reconforge.db.migrations import MIGRATIONS

router = APIRouter()


@router.get("/health")
def health(request: Request) -> dict[str, object]:
    """Return local API health without exposing secrets or environment data."""

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


@router.get("/version")
def version() -> dict[str, str]:
    """Return package and API version metadata."""

    return {
        "package": "reconforge-erp",
        "version": __version__,
        "api_version": "v1",
        "scope": "local/self-hosted foundation",
    }
