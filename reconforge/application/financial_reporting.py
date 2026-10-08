"""Backend-neutral use-case port for reviewed classifications and opening balances."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.financial_reporting import AccountClassification, OpeningPreparation, ReportingScope


class FinancialReportingRepository(Protocol):
    def prepare_map(
        self,
        scope: ReportingScope,
        *,
        name: str,
        accounts: Sequence[AccountClassification],
        command_id: str,
        actor: PostingActor,
    ) -> dict[str, Any]: ...
    def review_map(
        self, map_id: str, *, expected_digest: str, reason: str, command_id: str, actor: PostingActor
    ) -> dict[str, Any]: ...
    def get_map(self, map_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def list_maps(self, scope: ReportingScope, *, actor: PostingActor) -> list[dict[str, Any]]: ...
    def prepare_opening(
        self, request: OpeningPreparation, *, command_id: str, actor: PostingActor
    ) -> dict[str, Any]: ...
    def get_opening(self, opening_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def review_opening(
        self, opening_id: str, *, expected_digest: str, reason: str, command_id: str, actor: PostingActor
    ) -> dict[str, Any]: ...
    def post_opening(
        self, opening_id: str, *, expected_digest: str, reason: str, command_id: str, actor: PostingActor
    ) -> dict[str, Any]: ...
    def report(
        self,
        *,
        map_id: str,
        period_id: str,
        as_of_date: str,
        organization_code: str,
        entity_code: str,
        actor: PostingActor,
    ) -> dict[str, Any]: ...


class FinancialReportingApplicationService:
    """Expose one typed persistence port; financial arithmetic remains in the domain."""

    def __init__(self, repository: FinancialReportingRepository) -> None:
        self.repository = repository

    def prepare_map(
        self,
        scope: ReportingScope,
        *,
        name: str,
        accounts: Sequence[AccountClassification],
        command_id: str,
        actor: PostingActor,
    ) -> dict[str, Any]:
        return self.repository.prepare_map(scope, name=name, accounts=accounts, command_id=command_id, actor=actor)

    def review_map(
        self, map_id: str, *, expected_digest: str, reason: str, command_id: str, actor: PostingActor
    ) -> dict[str, Any]:
        return self.repository.review_map(
            map_id, expected_digest=expected_digest, reason=reason, command_id=command_id, actor=actor
        )

    def get_map(self, map_id: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.get_map(map_id, actor=actor)

    def list_maps(self, scope: ReportingScope, *, actor: PostingActor) -> list[dict[str, Any]]:
        return self.repository.list_maps(scope, actor=actor)

    def prepare_opening(self, request: OpeningPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.prepare_opening(request, command_id=command_id, actor=actor)

    def get_opening(self, opening_id: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.get_opening(opening_id, actor=actor)

    def review_opening(
        self, opening_id: str, *, expected_digest: str, reason: str, command_id: str, actor: PostingActor
    ) -> dict[str, Any]:
        return self.repository.review_opening(
            opening_id, expected_digest=expected_digest, reason=reason, command_id=command_id, actor=actor
        )

    def post_opening(
        self, opening_id: str, *, expected_digest: str, reason: str, command_id: str, actor: PostingActor
    ) -> dict[str, Any]:
        return self.repository.post_opening(
            opening_id, expected_digest=expected_digest, reason=reason, command_id=command_id, actor=actor
        )

    def report(
        self,
        *,
        map_id: str,
        period_id: str,
        as_of_date: str,
        organization_code: str,
        entity_code: str,
        actor: PostingActor,
    ) -> dict[str, Any]:
        return self.repository.report(
            map_id=map_id,
            period_id=period_id,
            as_of_date=as_of_date,
            organization_code=organization_code,
            entity_code=entity_code,
            actor=actor,
        )
