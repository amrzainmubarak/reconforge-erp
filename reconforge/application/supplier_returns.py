"""Governed native receipt inverse and supplier debit use cases."""
from __future__ import annotations

from typing import Any

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.supplier_returns import SupplierReturnPreparation
from reconforge.ports.supplier_returns import SupplierReturnsRepository


class SupplierReturnsService:
    def __init__(self, repository: SupplierReturnsRepository) -> None:
        self.repository = repository

    def prepare(self, request: SupplierReturnPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.prepare(request, command_id=command_id, actor=actor)

    def get(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.get(plan_id, actor=actor)

    def list_plans(self, order_id: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.list_plans(order_id, actor=actor)

    def review(self, plan_id: str, *, expected_plan_digest: str, command_id: str,
               reason: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.review(plan_id, expected_plan_digest=expected_plan_digest,
                                      command_id=command_id, reason=reason, actor=actor)

    def post(self, plan_id: str, *, expected_plan_digest: str, command_id: str,
             reason: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.post(plan_id, expected_plan_digest=expected_plan_digest,
                                    command_id=command_id, reason=reason, actor=actor)

    def cancel(self, plan_id: str, *, expected_plan_digest: str, command_id: str,
               reason: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.cancel(plan_id, expected_plan_digest=expected_plan_digest,
                                      command_id=command_id, reason=reason, actor=actor)
