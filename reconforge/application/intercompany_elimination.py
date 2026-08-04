"""Application boundary for the deterministic intercompany elimination artifact."""

from __future__ import annotations

from reconforge.domain.intercompany_elimination import (
    IntercompanyEliminationInputLine,
    IntercompanyEliminationResult,
    prepare_intercompany_eliminations,
)


class IntercompanyEliminationApplicationService:
    """Expose the pure elimination builder without adding persistence or posting."""

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
