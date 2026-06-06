"""Health and version routes for the local API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from reconforge import __version__
from reconforge.db import DatabaseError, database_status
from reconforge.db.migrations import MIGRATIONS

router = APIRouter()


@router.get("/health")
def health(request: Request) -> dict[str, object]:
    """Return local API health without exposing secrets or environment data."""

    db_path = request.app.state.db_path
    database_reachable = False
    schema_version = 0
    try:
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
            "path_summary": getattr(db_path, "name", "local sqlite database"),
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
