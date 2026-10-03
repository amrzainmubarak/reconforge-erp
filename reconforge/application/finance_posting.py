"""Complete transaction-owning port for explicit operational finance effects."""

from __future__ import annotations

from typing import Any, Protocol

from reconforge.domain.finance_posting import PostingActor


class FinancePostingRepositoryProtocol(Protocol):
    def preview(self, entry_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def post(
        self, entry_id: str, *, command_id: str, expected_validation_digest: str, reason: str, actor: PostingActor
    ) -> dict[str, Any]: ...
    def prepare_reversal(
        self,
        effect_id: str,
        *,
        command_id: str,
        entry_number: str,
        period_id: str,
        posting_date: str,
        reason: str,
        actor: PostingActor,
    ) -> dict[str, Any]: ...
    def get_effect(self, effect_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def posted_trial_balance(
        self,
        *,
        period_id: str,
        organization_code: str,
        entity_code: str,
        workspace: str = "default",
        actor: PostingActor,
    ) -> dict[str, Any]: ...


class FinancePostingApplicationService:
    """Delegate one command to an adapter owning its one atomic transaction."""

    def __init__(self, repository: FinancePostingRepositoryProtocol) -> None:
        self.repository = repository

    def preview(self, entry_id: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.preview(entry_id, actor=actor)

    def post(
        self, entry_id: str, *, command_id: str, expected_validation_digest: str, reason: str, actor: PostingActor
    ) -> dict[str, Any]:
        return self.repository.post(
            entry_id,
            command_id=command_id,
            expected_validation_digest=expected_validation_digest,
            reason=reason,
            actor=actor,
        )

    def prepare_reversal(
        self,
        effect_id: str,
        *,
        command_id: str,
        entry_number: str,
        period_id: str,
        posting_date: str,
        reason: str,
        actor: PostingActor,
    ) -> dict[str, Any]:
        return self.repository.prepare_reversal(
            effect_id,
            command_id=command_id,
            entry_number=entry_number,
            period_id=period_id,
            posting_date=posting_date,
            reason=reason,
            actor=actor,
        )

    def get_effect(self, effect_id: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.get_effect(effect_id, actor=actor)

    def posted_trial_balance(
        self,
        *,
        period_id: str,
        organization_code: str,
        entity_code: str,
        workspace: str = "default",
        actor: PostingActor,
    ) -> dict[str, Any]:
        return self.repository.posted_trial_balance(
            period_id=period_id,
            organization_code=organization_code,
            entity_code=entity_code,
            workspace=workspace,
            actor=actor,
        )
