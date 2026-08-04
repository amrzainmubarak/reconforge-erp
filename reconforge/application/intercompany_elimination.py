"""Application boundary for the deterministic intercompany elimination artifact."""

from __future__ import annotations

from reconforge.domain.intercompany_elimination import (
    IntercompanyEliminationInputLine,
    IntercompanyEliminationResult,
    prepare_intercompany_eliminations,
)


class IntercompanyEliminationApplicationService:
    """Build and persist an immutable, non-posting elimination artifact."""

    def __init__(self, repository: object | None = None) -> None:
        self.repository = repository

    @staticmethod
    def prepare(
        lines: tuple[IntercompanyEliminationInputLine, ...],
        *,
        reporting_currency: str,
        prepared_by: str,
        prepared_at: str,
        version: str = "1.0.0",
    ) -> IntercompanyEliminationResult:
        return prepare_intercompany_eliminations(
            lines,
            reporting_currency=reporting_currency,
            prepared_by=prepared_by,
            prepared_at=prepared_at,
            version=version,
        )

    def prepare_and_persist(
        self,
        lines: tuple[IntercompanyEliminationInputLine, ...],
        *,
        reporting_currency: str,
        prepared_by: str,
        prepared_at: str,
        version: str = "1.0.0",
        workspace: str,
        actor_label: str,
    ) -> dict[str, object]:
        if self.repository is None or not hasattr(self.repository, "persist"):
            raise TypeError("An intercompany elimination repository is required for persistence.")
        result = self.prepare(
            lines,
            reporting_currency=reporting_currency,
            prepared_by=prepared_by,
            prepared_at=prepared_at,
            version=version,
        )
        return self.repository.persist(
            lines,
            result,
            workspace=workspace,
            actor_label=actor_label,
        )
