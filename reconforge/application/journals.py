"""Backend-neutral journal control application boundary."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class JournalImportResult:
    """Journal import result without a persistence dependency."""

    source_path: Path
    imported_rows: int


class JournalControlRepositoryProtocol(Protocol):
    """Persistence and policy port for journal control use cases."""

    def import_journals(
        self,
        input_path: Path | str,
        *,
        workspace: str = "default",
        default_period: str = "current",
        default_entity: str = "local",
        actor_label: str = "local-cli",
    ) -> JournalImportResult: ...

    def policy_run(
        self,
        *,
        workspace: str = "default",
        period_name: str = "",
        period_end: str = "",
        high_value_threshold: object = Decimal("100000"),
        high_risk_accounts: str = "",
        actor_label: str = "local-cli",
    ) -> int: ...

    def exceptions(self, *, period_name: str = "") -> list[dict[str, Any]]: ...

    def report(self) -> dict[str, Any]: ...


class JournalControlApplicationService:
    """Coordinate journal controls without importing a database adapter."""

    def __init__(self, repository: JournalControlRepositoryProtocol) -> None:
        self.repository = repository

    def import_journals(
        self,
        input_path: Path | str,
        *,
        workspace: str = "default",
        default_period: str = "current",
        default_entity: str = "local",
        actor_label: str = "local-cli",
    ) -> JournalImportResult:
        return self.repository.import_journals(
            input_path,
            workspace=workspace,
            default_period=default_period,
            default_entity=default_entity,
            actor_label=actor_label,
        )

    def policy_run(
        self,
        *,
        workspace: str = "default",
        period_name: str = "",
        period_end: str = "",
        high_value_threshold: object = Decimal("100000"),
        high_risk_accounts: str = "",
        actor_label: str = "local-cli",
    ) -> int:
        return self.repository.policy_run(
            workspace=workspace,
            period_name=period_name,
            period_end=period_end,
            high_value_threshold=high_value_threshold,
            high_risk_accounts=high_risk_accounts,
            actor_label=actor_label,
        )

    def exceptions(self, *, period_name: str = "") -> list[dict[str, Any]]:
        return self.repository.exceptions(period_name=period_name)

    def report(self) -> dict[str, Any]:
        return self.repository.report()
