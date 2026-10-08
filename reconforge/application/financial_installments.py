"""Backend-neutral command port for reviewed native AP installments."""

from typing import Any, Protocol

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.financial_installments import FinancialInstallmentPreparation


class FinancialInstallmentsRepository(Protocol):
    def prepare(self, request: FinancialInstallmentPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def get(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def review(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str,
               actor: PostingActor) -> dict[str, Any]: ...
    def post(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str,
             actor: PostingActor) -> dict[str, Any]: ...


class FinancialInstallmentsApplicationService:
    def __init__(self, repository: FinancialInstallmentsRepository) -> None:
        self.repository = repository

    def prepare(self, request: FinancialInstallmentPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.prepare(request, command_id=command_id, actor=actor)

    def get(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.get(plan_id, actor=actor)

    def review(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str,
               actor: PostingActor) -> dict[str, Any]:
        return self.repository.review(plan_id, expected_plan_digest=expected_plan_digest,
                                      command_id=command_id, reason=reason, actor=actor)

    def post(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str,
             actor: PostingActor) -> dict[str, Any]:
        return self.repository.post(plan_id, expected_plan_digest=expected_plan_digest,
                                    command_id=command_id, reason=reason, actor=actor)
