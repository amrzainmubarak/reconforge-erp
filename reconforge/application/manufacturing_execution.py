"""Backend-neutral service boundary for governed native production."""
from collections.abc import Mapping
from typing import Any

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.manufacturing_execution import BomPreparation, OrderPreparation
from reconforge.ports.manufacturing_execution import ManufacturingExecutionRepository


class ManufacturingExecutionService:
    def __init__(self, repository: ManufacturingExecutionRepository) -> None:
        self.repository = repository

    def prepare_bom(self, request: BomPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.prepare_bom(request, command_id=command_id, actor=actor)

    def approve_bom(self, bom_id: str, *, expected_digest: str, command_id: str,
                    reason: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.approve_bom(bom_id, expected_digest=expected_digest, command_id=command_id, reason=reason, actor=actor)

    def create_order(self, request: OrderPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.create_order(request, command_id=command_id, actor=actor)

    def get_order(self, order_id: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.get_order(order_id, actor=actor)

    def get_requirement(self, requirement_id: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.get_requirement(requirement_id, actor=actor)

    def list_orders(self, scope: Mapping[str, Any], *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.list_orders(scope, actor=actor)

    def act(self, order_id: str, operation: str, *, expected_digest: str, command_id: str,
            reason: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.act(order_id, operation, expected_digest=expected_digest, command_id=command_id, reason=reason, actor=actor)

    def prepare_completion(self, order_id: str, *, good_quantity: str, scrap_quantity: str,
                           period_id: str, posting_date: str, command_id: str, reason: str,
                           actor: PostingActor) -> dict[str, Any]:
        return self.repository.prepare_completion(order_id, good_quantity=good_quantity, scrap_quantity=scrap_quantity,
            period_id=period_id, posting_date=posting_date, command_id=command_id, reason=reason, actor=actor)

    def act_completion(self, completion_id: str, operation: str, *, expected_digest: str,
                       command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.act_completion(completion_id, operation, expected_digest=expected_digest,
            command_id=command_id, reason=reason, actor=actor)
