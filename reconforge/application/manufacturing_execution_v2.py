"""Governed actual costing, quality holds and original-source inspection use cases."""
from collections.abc import Mapping
from typing import Any

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.manufacturing_execution_v2 import (
    ManufacturingOrderPreparation,
    RoutingPreparation,
    WorkcenterPreparation,
)
from reconforge.ports.manufacturing_execution_v2 import ManufacturingExecutionV2Repository


class ManufacturingExecutionV2Service:
    def __init__(self, repository: ManufacturingExecutionV2Repository) -> None:
        self.repository = repository

    def create_workcenter(self, request: WorkcenterPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.create_workcenter(request, command_id=command_id, actor=actor)

    def create_routing(self, request: RoutingPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.create_routing(request, command_id=command_id, actor=actor)

    def approve_definition(self, identifier: str, *, expected_digest: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.approve_definition(identifier, expected_digest=expected_digest, command_id=command_id, reason=reason, actor=actor)

    def create_order(self, request: ManufacturingOrderPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.create_order(request, command_id=command_id, actor=actor)

    def act_order(self, identifier: str, operation: str, *, expected_digest: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.act_order(identifier, operation, expected_digest=expected_digest, command_id=command_id, reason=reason, actor=actor)

    def produce(self, identifier: str, *, output_quantity: str, operations: list[dict[str, Any]], period_id: str, posting_date: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.produce(identifier, output_quantity=output_quantity, operations=operations, period_id=period_id, posting_date=posting_date, command_id=command_id, reason=reason, actor=actor)

    def act_production(self, identifier: str, operation: str, *, expected_digest: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.act_production(identifier, operation, expected_digest=expected_digest, command_id=command_id, reason=reason, actor=actor)

    def inspect(self, identifier: str, *, accepted_quantity: str, rejected_quantity: str, inspection_reference: str, period_id: str, posting_date: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.inspect(identifier, accepted_quantity=accepted_quantity, rejected_quantity=rejected_quantity, inspection_reference=inspection_reference, period_id=period_id, posting_date=posting_date, command_id=command_id, reason=reason, actor=actor)

    def act_inspection(self, identifier: str, operation: str, *, expected_digest: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.act_inspection(identifier, operation, expected_digest=expected_digest, command_id=command_id, reason=reason, actor=actor)

    def get_order(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.get_order(identifier, actor=actor)

    def list_sources(self, scope: Mapping[str, Any], *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.list_sources(scope, actor=actor)
