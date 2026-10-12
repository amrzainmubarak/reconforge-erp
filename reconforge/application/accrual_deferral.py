"""One source-owning adapter port for governed AD1 voucher schedules."""

from typing import Any, Protocol

from reconforge.domain.accrual_deferral import AccrualDeferralPreparation
from reconforge.domain.finance_posting import PostingActor


class AccrualDeferralRepositoryProtocol(Protocol):
    def prepare_source(self, request: AccrualDeferralPreparation, *, command_id: str,
                       actor: PostingActor) -> dict[str, Any]: ...
    def prepare_tranche(self, source_id: str, *, tranche_id: str, command_id: str,
                        actor: PostingActor) -> dict[str, Any]: ...
    def prepare_reversal(self, source_id: str, *, original_plan_id: str, period_id: str,
                         posting_date: str, reason: str, command_id: str,
                         actor: PostingActor) -> dict[str, Any]: ...
    def prepare_cancellation(self, source_id: str, *, reason: str,
                             command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def review(self, plan_id: str, *, expected_plan_digest: str, reason: str,
               command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def post(self, plan_id: str, *, expected_plan_digest: str, reason: str,
             command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def get_source(self, source_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def get_plan(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def evidence(self, source_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def plan_evidence(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def list_sources(self, *, workspace_id: str, organization_id: str, legal_entity_id: str,
                     after: str, actor: PostingActor) -> dict[str, Any]: ...


class AccrualDeferralApplicationService:
    """Delegate one authenticated command to one whole adapter transaction."""

    def __init__(self, repository: AccrualDeferralRepositoryProtocol) -> None:
        self.repository = repository

    def prepare_source(self, request: AccrualDeferralPreparation, *, command_id: str,
                       actor: PostingActor) -> dict[str, Any]:
        return self.repository.prepare_source(request, command_id=command_id, actor=actor)

    def prepare_tranche(self, source_id: str, *, tranche_id: str, command_id: str,
                        actor: PostingActor) -> dict[str, Any]:
        return self.repository.prepare_tranche(source_id, tranche_id=tranche_id, command_id=command_id, actor=actor)

    def prepare_reversal(self, source_id: str, *, original_plan_id: str, period_id: str,
                         posting_date: str, reason: str, command_id: str,
                         actor: PostingActor) -> dict[str, Any]:
        return self.repository.prepare_reversal(source_id, original_plan_id=original_plan_id, period_id=period_id,
            posting_date=posting_date, reason=reason, command_id=command_id, actor=actor)

    def prepare_cancellation(self, source_id: str, *, reason: str,
                             command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.prepare_cancellation(source_id, reason=reason, command_id=command_id, actor=actor)

    def review(self, plan_id: str, *, expected_plan_digest: str, reason: str,
               command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.review(plan_id, expected_plan_digest=expected_plan_digest, reason=reason,
            command_id=command_id, actor=actor)

    def post(self, plan_id: str, *, expected_plan_digest: str, reason: str,
             command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.post(plan_id, expected_plan_digest=expected_plan_digest, reason=reason,
            command_id=command_id, actor=actor)

    def get_source(self, source_id: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.get_source(source_id, actor=actor)

    def get_plan(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.get_plan(plan_id, actor=actor)

    def evidence(self, source_id: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.evidence(source_id, actor=actor)

    def plan_evidence(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.plan_evidence(plan_id, actor=actor)

    def list_sources(self, *, workspace_id: str, organization_id: str, legal_entity_id: str,
                     after: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.list_sources(workspace_id=workspace_id, organization_id=organization_id,
            legal_entity_id=legal_entity_id, after=after, actor=actor)
