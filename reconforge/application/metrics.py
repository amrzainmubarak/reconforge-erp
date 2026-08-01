"""Backend-neutral dashboard metric use cases."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol

from reconforge.domain.models import utc_now_text
from reconforge.platform.common import platform_id


class MetricsRepositoryProtocol(Protocol):
    """Sanitized metric computations exposed by a persistence adapter."""

    def verify_compute_permission(self, actor_label: str) -> None: ...

    def ensure_workspace(self, workspace_name: str) -> str: ...

    def close_completion(self, workspace_id: str, period_name: str) -> Decimal: ...

    def unresolved_high_risk(self, workspace_id: str, period_name: str) -> Decimal: ...

    def review_aging(self, workspace_id: str, period_name: str) -> Decimal: ...

    def evidence_coverage(self, workspace_id: str) -> Decimal: ...

    def control_effectiveness(self, workspace_id: str, period_name: str) -> Decimal: ...

    def match_rate(self, workspace_id: str) -> Decimal: ...

    def exception_aging(self, workspace_id: str, period_name: str) -> Decimal: ...

    def period_readiness(self, workspace_id: str, period_name: str) -> Decimal: ...

    def dashboard(self, period_name: str) -> list[dict[str, Any]]: ...

    def lineage(self) -> list[dict[str, Any]]: ...

    def save_snapshots_and_audit(
        self,
        *,
        actor_label: str,
        workspace_id: str,
        period_name: str,
        snapshots: list[tuple[str, str, str, str]],
        computed_at: str,
        metric_count: int,
    ) -> None: ...


class MetricsApplicationService:
    """Compute and store local dashboard metrics without coupling to a backend."""

    def __init__(self, repository: MetricsRepositoryProtocol) -> None:
        self._repository = repository

    def compute(
        self, *, workspace: str = "default", period_name: str = "", actor_label: str = "local-cli"
    ) -> list[dict[str, Any]]:
        """Compute and store governed metric snapshots."""

        self._repository.verify_compute_permission(actor_label)
        workspace_id = self._repository.ensure_workspace(workspace)
        definitions = self._repository.lineage()
        values = {
            "close_completion": self._repository.close_completion(workspace_id, period_name),
            "unresolved_high_risk_exceptions": self._repository.unresolved_high_risk(workspace_id, period_name),
            "review_aging": self._repository.review_aging(workspace_id, period_name),
            "evidence_coverage": self._repository.evidence_coverage(workspace_id),
            "control_effectiveness": self._repository.control_effectiveness(workspace_id, period_name),
            "match_rate": self._repository.match_rate(workspace_id),
            "exception_aging": self._repository.exception_aging(workspace_id, period_name),
            "period_readiness": self._repository.period_readiness(workspace_id, period_name),
        }

        now = utc_now_text()
        snapshots = []
        for definition in definitions:
            key = str(definition["metric_key"])
            value = values.get(key, Decimal(0))
            value_text = format(value, "f")
            snapshot_id = platform_id("METS", workspace_id, key, period_name)
            snapshots.append((snapshot_id, key, value_text, str(definition["lineage"])))

        self._repository.save_snapshots_and_audit(
            actor_label=actor_label,
            workspace_id=workspace_id,
            period_name=period_name,
            snapshots=snapshots,
            computed_at=now,
            metric_count=len(values),
        )
        return self._repository.dashboard(period_name=period_name)

    def dashboard(self, *, period_name: str = "") -> list[dict[str, Any]]:
        """Return dashboard metric snapshots with definitions and lineage."""
        return self._repository.dashboard(period_name=period_name)

    def lineage(self) -> list[dict[str, Any]]:
        """Return governed metric definitions."""
        return self._repository.lineage()
