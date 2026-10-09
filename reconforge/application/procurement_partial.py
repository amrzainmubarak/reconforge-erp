"""Typed connection-free contract for owned partial procure-to-pay commands."""
from __future__ import annotations

from typing import Any, Protocol

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.procurement_operations import ProcurementPreparation
from reconforge.domain.procurement_partial import (
    MultilineInvoicePreparation,
    MultilineProcurementPreparation,
    PartialQuantityPreparation,
)


class ProcurementPartialRepository(Protocol):
    def create(self, request: ProcurementPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def act(self, order_id: str, operation: str, *, expected_version: int, command_id: str, reason: str,
            actor: PostingActor, document_id: str | None = None) -> dict[str, Any]: ...
    def prepare_receipt(self, order_id: str, request: PartialQuantityPreparation, *, expected_version: int,
                        command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def match_invoice(self, order_id: str, request: PartialQuantityPreparation, *, expected_version: int,
                      command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def get(self, order_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def list_orders(self, workspace: str, *, actor: PostingActor) -> list[dict[str, Any]]: ...
    def create_multiline(self, request: MultilineProcurementPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def prepare_receipt_line(self, order_id: str, line_id: str, request: PartialQuantityPreparation, *, expected_version: int,
                             command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def match_invoice_lines(self, order_id: str, request: MultilineInvoicePreparation, *, expected_version: int,
                            command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def order_page(self, workspace: str, *, actor: PostingActor, after: str = "", page_size: int = 25) -> dict[str, Any]: ...
    def document_page(self, order_id: str, *, receipt_after: int = 0, invoice_after: int = 0, actor: PostingActor) -> dict[str, Any]: ...
    def item_catalog_page(self, workspace: str, organization_id: str, *, actor: PostingActor, after: str = "", search: str = "") -> dict[str, Any]: ...


class ProcurementPartialApplicationService:
    def __init__(self, repository: ProcurementPartialRepository) -> None:
        self.repository = repository

    def create(self, request: ProcurementPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.create(request, command_id=command_id, actor=actor)

    def act(self, order_id: str, operation: str, *, expected_version: int, command_id: str, reason: str,
            actor: PostingActor, document_id: str | None = None) -> dict[str, Any]:
        return self.repository.act(order_id, operation, expected_version=expected_version, command_id=command_id,
                                   reason=reason, actor=actor, document_id=document_id)

    def prepare_receipt(self, order_id: str, request: PartialQuantityPreparation, *, expected_version: int,
                        command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.prepare_receipt(order_id, request, expected_version=expected_version, command_id=command_id, actor=actor)

    def match_invoice(self, order_id: str, request: PartialQuantityPreparation, *, expected_version: int,
                      command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.match_invoice(order_id, request, expected_version=expected_version, command_id=command_id, actor=actor)

    def get(self, order_id: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.get(order_id, actor=actor)

    def list_orders(self, workspace: str, *, actor: PostingActor) -> list[dict[str, Any]]:
        return self.repository.list_orders(workspace, actor=actor)

    def create_multiline(self, request: MultilineProcurementPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.create_multiline(request, command_id=command_id, actor=actor)

    def prepare_receipt_line(self, order_id: str, line_id: str, request: PartialQuantityPreparation, *, expected_version: int,
                             command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.prepare_receipt_line(order_id, line_id, request, expected_version=expected_version, command_id=command_id, actor=actor)

    def match_invoice_lines(self, order_id: str, request: MultilineInvoicePreparation, *, expected_version: int,
                            command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.match_invoice_lines(order_id, request, expected_version=expected_version, command_id=command_id, actor=actor)

    def order_page(self, workspace: str, *, actor: PostingActor, after: str = "", page_size: int = 25) -> dict[str, Any]:
        return self.repository.order_page(workspace, actor=actor, after=after, page_size=page_size)

    def document_page(self, order_id: str, *, receipt_after: int = 0, invoice_after: int = 0, actor: PostingActor) -> dict[str, Any]:
        return self.repository.document_page(order_id, actor=actor, receipt_after=receipt_after, invoice_after=invoice_after)
