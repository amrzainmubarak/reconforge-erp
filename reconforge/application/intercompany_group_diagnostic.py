"""Read-only diagnostic boundary for explicitly selected original group reports."""

from typing import Any, Protocol

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.intercompany_group_diagnostic import IntercompanyDiagnosticSelection


class IntercompanyGroupDiagnosticRepositoryProtocol(Protocol):
    def evidence(self, selection: IntercompanyDiagnosticSelection, *, actor: PostingActor) -> dict[str, Any]: ...


class IntercompanyGroupDiagnosticService:
    def __init__(self, repository: IntercompanyGroupDiagnosticRepositoryProtocol) -> None:
        self.repository = repository

    def evidence(self, selection: IntercompanyDiagnosticSelection, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.evidence(selection, actor=actor)

    def report(self, selection: IntercompanyDiagnosticSelection, *, actor: PostingActor) -> dict[str, Any]:
        return self.evidence(selection, actor=actor)["diagnostic"]
