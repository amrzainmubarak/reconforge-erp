"""Metric routes for the local API."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from reconforge.api.dependencies import get_local_db, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_metrics import execute_postgres_metrics, server_metrics_enabled
from reconforge.application.metrics import MetricsApplicationService
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.infrastructure.sqlite_metrics import SQLiteMetricsRepository
from reconforge.platform.common import PlatformError

router = APIRouter(prefix="/metrics", tags=["metrics"])

MetricsRead = Annotated[LocalUser, Depends(require_permission("metrics.read"))]


@router.get("/dashboard")
def dashboard(
    request: Request,
    current_user: MetricsRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    period: str = "",
) -> dict[str, object]:
    """Return governed local dashboard metrics."""

    try:
        if server_metrics_enabled(request):
            metrics = execute_postgres_metrics(
                request,
                lambda repository, _: MetricsApplicationService(repository).dashboard(period_name=period),
            )
        else:
            if connection is None:
                raise APIError(status_code=500, code="db_not_configured", message="Database not configured.")
            metrics = MetricsApplicationService(SQLiteMetricsRepository(connection)).dashboard(period_name=period)
    except (DatabaseError, PlatformError, RuntimeError) as exc:
        raise APIError(status_code=400, code="metrics_dashboard_failed", message=str(exc)) from exc
    return {"metrics": metrics}


@router.get("/lineage")
def lineage(
    request: Request,
    current_user: MetricsRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Return governed local metric lineage definitions."""

    try:
        if server_metrics_enabled(request):
            definitions = execute_postgres_metrics(
                request,
                lambda repository, _: MetricsApplicationService(repository).lineage(),
            )
        else:
            if connection is None:
                raise APIError(status_code=500, code="db_not_configured", message="Database not configured.")
            definitions = MetricsApplicationService(SQLiteMetricsRepository(connection)).lineage()
    except (DatabaseError, PlatformError, RuntimeError) as exc:
        raise APIError(status_code=400, code="metrics_lineage_failed", message=str(exc)) from exc
    return {"lineage": definitions}
