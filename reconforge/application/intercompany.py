"""Backend-neutral intercompany workflow boundary."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class IntercompanyImportResult:
    """Intercompany import result without a persistence dependency."""

    source_path: Path
    imported_rows: int


class IntercompanyRepositoryProtocol(Protocol):
    """Persistence and policy port for intercompany use cases."""

    def import_transactions(
        self,
        input_path: Path | str,
        *,
        workspace: str = "default",
        default_period: str = "current",
        actor_label: str = "local-cli",
    ) -> IntercompanyImportResult: ...

    def match(
        self,
        *,
        workspace: str = "default",
        period_name: str = "",
        tolerance: object = Decimal("0.01"),
        actor_label: str = "local-cli",
    ) -> int: ...

    def settle(
        self,
        case_id: str,
        *,
        settlement_status: str = "Settled",
        dispute_owner: str = "",
        evidence_note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def cases(self, *, status: str = "") -> list[dict[str, Any]]: ...

    def get_case(self, case_id: str) -> dict[str, Any]: ...


class IntercompanyApplicationService:
    """Coordinate intercompany workflows without importing a database adapter."""

    def __init__(self, repository: IntercompanyRepositoryProtocol) -> None:
        self.repository = repository

    def import_transactions(
        self,
        input_path: Path | str,
        *,
        workspace: str = "default",
        default_period: str = "current",
        actor_label: str = "local-cli",
    ) -> IntercompanyImportResult:
        return self.repository.import_transactions(
            input_path, workspace=workspace, default_period=default_period, actor_label=actor_label
        )

    def match(
        self,
        *,
        workspace: str = "default",
        period_name: str = "",
        tolerance: object = Decimal("0.01"),
        actor_label: str = "local-cli",
    ) -> int:
        return self.repository.match(
            workspace=workspace, period_name=period_name, tolerance=tolerance, actor_label=actor_label
        )

    def settle(
        self,
        case_id: str,
        *,
        settlement_status: str = "Settled",
        dispute_owner: str = "",
        evidence_note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.settle(
            case_id,
            settlement_status=settlement_status,
            dispute_owner=dispute_owner,
            evidence_note=evidence_note,
            actor_label=actor_label,
        )

    def cases(self, *, status: str = "") -> list[dict[str, Any]]:
        return self.repository.cases(status=status)

    def get_case(self, case_id: str) -> dict[str, Any]:
        return self.repository.get_case(case_id)
