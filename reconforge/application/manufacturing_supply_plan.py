"""Application boundary for actual engineering demand before stock exists."""
from collections.abc import Mapping
from typing import Any

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.manufacturing_execution_v2 import ManufacturingOrderPreparation
from reconforge.domain.manufacturing_supply_plan import SupplyPlanPreparation
from reconforge.domain.procurement_partial import MultilineInvoicePreparation, PartialQuantityPreparation
from reconforge.domain.procurement_sourcing import RequisitionPreparation, SupplierQuotationPreparation
from reconforge.ports.manufacturing_supply_plan import ManufacturingSupplyPlanRepository


class ManufacturingSupplyPlanService:
    def __init__(self, repository: ManufacturingSupplyPlanRepository) -> None:
        self.repository = repository

    def create(self, request: SupplyPlanPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request.payload()
        return self.repository.create(request, command_id=command_id, actor=actor)

    def approve(self, identifier: str, *, expected_digest: str, command_id: str, reason: str,
                actor: PostingActor) -> dict[str, Any]:
        return self.repository.approve(identifier, expected_digest=expected_digest, command_id=command_id,
                                       reason=reason, actor=actor)

    def cancel(self, identifier: str, *, expected_digest: str, command_id: str, reason: str,
               actor: PostingActor) -> dict[str, Any]:
        return self.repository.cancel(identifier, expected_digest=expected_digest, command_id=command_id,
                                      reason=reason, actor=actor)

    def get(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.get(identifier, actor=actor)

    def get_requirement(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.get_requirement(identifier, actor=actor)

    def list_plans(self, scope: Mapping[str, Any], *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.list_plans(scope, actor=actor)

    def get_requisition(self, identifier: str, requisition_id: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.get_requisition(identifier, requisition_id, actor=actor)

    def get_purchase(self, identifier: str, order_id: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.get_purchase(identifier, order_id, actor=actor)

    def create_requisition(self, identifier: str, request: RequisitionPreparation, *, requirement_ids: tuple[str, ...],
                           expected_digest: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.create_requisition(identifier, request, requirement_ids=requirement_ids,
            expected_digest=expected_digest, command_id=command_id, actor=actor)

    def act_requisition(self, identifier: str, requisition_id: str, operation: str, *, expected_version: int,
                        command_id: str, reason: str, actor: PostingActor, expected_budget_version: int | None = None,
                        quotation: SupplierQuotationPreparation | None = None) -> dict[str, Any]:
        return self.repository.act_requisition(identifier, requisition_id, operation, expected_version=expected_version,
            command_id=command_id, reason=reason, actor=actor, expected_budget_version=expected_budget_version, quotation=quotation)

    def procurement_operation(self, identifier: str, order_id: str, operation: str, *, expected_version: int,
                              command_id: str, reason: str, actor: PostingActor, line_id: str | None = None,
                              document_id: str | None = None, quantity_request: PartialQuantityPreparation | None = None,
                              invoice_request: MultilineInvoicePreparation | None = None,
                              expected_budget_version: int | None = None) -> dict[str, Any]:
        return self.repository.procurement_operation(identifier, order_id, operation, expected_version=expected_version,
            command_id=command_id, reason=reason, actor=actor, line_id=line_id, document_id=document_id,
            quantity_request=quantity_request, invoice_request=invoice_request, expected_budget_version=expected_budget_version)

    def handoff(self, identifier: str, request: ManufacturingOrderPreparation, *, expected_digest: str,
                command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        request.payload()
        return self.repository.handoff(identifier, request, expected_digest=expected_digest, command_id=command_id, reason=reason, actor=actor)
