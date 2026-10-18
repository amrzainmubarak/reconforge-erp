"""Read-only source reconciliation uses the existing owner and ledger ports."""

from typing import Any

from reconforge.application.ports_project_source_reconciliation import ProjectSourceReconciliationRepository
from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.project_source_reconciliation import ProjectSourceSelection


class ProjectSourceReconciliationService:
    def __init__(self, repository: ProjectSourceReconciliationRepository) -> None:
        self.repository = repository

    def report(self, selection: ProjectSourceSelection, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.report(selection, actor=actor)

    def close_diagnostics(self, selection: ProjectSourceSelection, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.close_diagnostics(selection, actor=actor)
