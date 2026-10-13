"""Read one original paired source; the existing IC2 owner governs every effect."""

from typing import Any, Protocol

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.intercompany_cashflow import SourceCashOpening


class IntercompanyCashflowRepositoryProtocol(Protocol):
    def evidence(self, source_id: str, *, opening: SourceCashOpening, actor: PostingActor) -> dict[str, Any]: ...


class IntercompanyCashflowApplicationService:
    def __init__(self, repository: IntercompanyCashflowRepositoryProtocol) -> None:
        self.repository = repository

    def evidence(self, source_id: str, *, opening: SourceCashOpening, actor: PostingActor) -> dict[str, Any]:
        return self.repository.evidence(source_id, opening=opening, actor=actor)

    def report(self, source_id: str, *, opening: SourceCashOpening, actor: PostingActor) -> dict[str, Any]:
        return self.evidence(source_id, opening=opening, actor=actor)["cashflow"]
