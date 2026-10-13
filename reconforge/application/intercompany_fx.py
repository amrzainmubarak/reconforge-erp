"""Backend-neutral use-case port for one governed paired foreign trade owner."""

from collections.abc import Mapping
from typing import Any, Protocol

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.intercompany_fx import IntercompanyFxPreparation
from reconforge.domain.operational_fx_tax import HistoricalRate


class IntercompanyFxRepositoryProtocol(Protocol):
    def prepare(self, request: IntercompanyFxPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]: ...

    def prepare_settlement(self, source_id: str, *, transaction_minor: int, rates: Mapping[str, HistoricalRate],
                           period_ids: Mapping[str, str], posting_date: str, reason: str,
                           command_id: str, actor: PostingActor) -> dict[str, Any]: ...

    def prepare_revaluation(self, source_id: str, *, rates: Mapping[str, HistoricalRate], period_ids: Mapping[str, str],
                            posting_date: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]: ...

    def prepare_revaluation_reversal(self, source_id: str, *, original_revaluation_id: str,
                                     period_ids: Mapping[str, str], posting_date: str, reason: str,
                                     command_id: str, actor: PostingActor) -> dict[str, Any]: ...

    def prepare_elimination(self, source_id: str, *, closing_rates: Mapping[str, HistoricalRate],
                            income_rates: Mapping[str, Mapping[str, HistoricalRate]], period_ids: Mapping[str, str],
                            posting_date: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]: ...

    def review(self, plan_id: str, *, expected_plan_digest: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def post(self, plan_id: str, *, expected_plan_digest: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def get_source(self, source_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def list_sources(self, *, workspace_id: str, organization_id: str, after: str, actor: PostingActor) -> dict[str, Any]: ...
    def get_plan(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def evidence(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def native_evidence_bundle(self, source_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def report(self, source_id: str, *, actor: PostingActor) -> dict[str, Any]: ...


class IntercompanyFxService:
    """Application composition preserves one native repository transaction."""

    def __init__(self, repository: IntercompanyFxRepositoryProtocol) -> None:
        self.repository = repository

    def prepare(self, request: IntercompanyFxPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.prepare(request, command_id=command_id, actor=actor)

    def review(self, plan_id: str, *, expected_plan_digest: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.review(plan_id, expected_plan_digest=expected_plan_digest, reason=reason, command_id=command_id, actor=actor)

    def post(self, plan_id: str, *, expected_plan_digest: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.post(plan_id, expected_plan_digest=expected_plan_digest, reason=reason, command_id=command_id, actor=actor)

    def native_evidence_bundle(self, source_id: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.native_evidence_bundle(source_id, actor=actor)

    def prepare_settlement(self, source_id: str, *, transaction_minor: int, rates: Mapping[str, HistoricalRate],
                           period_ids: Mapping[str, str], posting_date: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.prepare_settlement(source_id, transaction_minor=transaction_minor, rates=rates, period_ids=period_ids,
            posting_date=posting_date, reason=reason, command_id=command_id, actor=actor)

    def prepare_revaluation(self, source_id: str, *, rates: Mapping[str, HistoricalRate], period_ids: Mapping[str, str],
                            posting_date: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.prepare_revaluation(source_id, rates=rates, period_ids=period_ids, posting_date=posting_date,
            reason=reason, command_id=command_id, actor=actor)

    def prepare_revaluation_reversal(self, source_id: str, *, original_revaluation_id: str, period_ids: Mapping[str, str],
                                     posting_date: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.prepare_revaluation_reversal(source_id, original_revaluation_id=original_revaluation_id, period_ids=period_ids,
            posting_date=posting_date, reason=reason, command_id=command_id, actor=actor)

    def prepare_elimination(self, source_id: str, *, closing_rates: Mapping[str, HistoricalRate],
                            income_rates: Mapping[str, Mapping[str, HistoricalRate]], period_ids: Mapping[str, str], posting_date: str,
                            reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.prepare_elimination(source_id, closing_rates=closing_rates, income_rates=income_rates, period_ids=period_ids,
            posting_date=posting_date, reason=reason, command_id=command_id, actor=actor)
