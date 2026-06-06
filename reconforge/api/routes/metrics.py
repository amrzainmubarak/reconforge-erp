"""Metric routes for the local API."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends

from reconforge.api.dependencies import get_db, require_permission
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.platform.common import PlatformError
from reconforge.platform.metrics import MetricsService

router = APIRouter(prefix="/metrics", tags=["metrics"])

MetricsRead = Annotated[LocalUser, Depends(require_permission("metrics.read"))]


@router.get("/dashboard")
def dashboard(
    current_user: MetricsRead,
    connection: sqlite3.Connection = Depends(get_db),
    period: str = "",
) -> dict[str, object]:
    """Return governed local dashboard metrics."""

    try:
        metrics = MetricsService(connection).dashboard(period_name=period)
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="metrics_dashboard_failed", message=str(exc)) from exc
    return {"metrics": metrics}


@router.get("/lineage")
def lineage(
    current_user: MetricsRead,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Return governed local metric lineage definitions."""

    try:
        definitions = MetricsService(connection).lineage()
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="metrics_lineage_failed", message=str(exc)) from exc
    return {"lineage": definitions}
