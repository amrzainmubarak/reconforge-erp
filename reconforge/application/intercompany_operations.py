"""Backend-neutral port for atomic native intercompany operation owners."""

from typing import Any, Protocol

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.intercompany_operations import IntercompanyPreparation


class IntercompanyOperationsRepositoryProtocol(Protocol):
    def prepare(self, request: IntercompanyPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def prepare_settlement(self, source_id: str, *, amount_minor: int, period_id: str, posting_date: str,
                           reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def prepare_elimination(self, source_id: str, *, period_id: str, posting_date: str,
                            reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def review(self, plan_id: str, *, expected_plan_digest: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def post(self, plan_id: str, *, expected_plan_digest: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def get_source(self, source_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def get_plan(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def evidence(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def report(self, source_id: str, *, seller_map_id: str, buyer_map_id: str, adjustment_map_id: str,
               period_id: str, as_of_date: str, actor: PostingActor) -> dict[str, Any]: ...


class IntercompanyOperationsService:
    """Expose the repository port without backend or ledger construction."""

    def __init__(self, repository: IntercompanyOperationsRepositoryProtocol) -> None:
        self.repository = repository

    def prepare(self, request: IntercompanyPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.prepare(request, command_id=command_id, actor=actor)
