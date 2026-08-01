"""Compatibility adapter for local dashboard metrics."""

from __future__ import annotations

import sqlite3
from typing import Any

from reconforge.application.metrics import MetricsApplicationService
from reconforge.infrastructure.sqlite_metrics import SQLiteMetricsRepository


class MetricsService:
    """Preserve the historical connection-based API over explicit ports."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._application = MetricsApplicationService(SQLiteMetricsRepository(connection))

    def compute(
        self, *, workspace: str = "default", period_name: str = "", actor_label: str = "local-cli"
    ) -> list[dict[str, Any]]:
        return self._application.compute(workspace=workspace, period_name=period_name, actor_label=actor_label)

    def dashboard(self, *, period_name: str = "") -> list[dict[str, Any]]:
        return self._application.dashboard(period_name=period_name)

    def lineage(self) -> list[dict[str, Any]]:
        return self._application.lineage()
