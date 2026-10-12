"""Connection-free use cases for governed service sales and revenue."""

from __future__ import annotations

from typing import Any, Protocol

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.sales_revenue import SalesInvoicePreparation, SalesQuotation


class SalesRevenueRepositoryProtocol(Protocol):
    def options(self, *, actor: PostingActor) -> dict[str, Any]: ...
    def create(self, quotation: SalesQuotation, *, command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def get(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def list(self, *, actor: PostingActor, after: str = "") -> dict[str, Any]: ...
    def transition(
        self,
        identifier: str,
        *,
        operation: str,
        expected_version: int,
        reason: str,
        command_id: str,
        actor: PostingActor,
        reference: str = "",
        business_date: str = "",
    ) -> dict[str, Any]: ...
    def prepare_invoice(
        self,
        identifier: str,
        preparation: SalesInvoicePreparation,
        *,
        expected_version: int,
        command_id: str,
        actor: PostingActor,
    ) -> dict[str, Any]: ...
    def review_invoice(
        self, identifier: str, *, expected_version: int, command_id: str, reason: str, actor: PostingActor
    ) -> dict[str, Any]: ...
    def post_invoice(
        self, identifier: str, *, expected_version: int, command_id: str, reason: str, actor: PostingActor
    ) -> dict[str, Any]: ...
    def prepare_collection(
        self,
        identifier: str,
        *,
        expected_version: int,
        command_id: str,
        reason: str,
        actor: PostingActor,
        receipt_number: str,
        receipt_date: str,
        journal_code: str,
        period_id: str,
        cash_account_code: str,
    ) -> dict[str, Any]: ...
    def review_collection(
        self, identifier: str, *, expected_version: int, command_id: str, reason: str, actor: PostingActor
    ) -> dict[str, Any]: ...
    def post_collection(
        self, identifier: str, *, expected_version: int, command_id: str, reason: str, actor: PostingActor
    ) -> dict[str, Any]: ...


class SalesRevenueApplicationService:
    """Use the complete source owner; no individual financial participants escape."""

    def __init__(self, repository: SalesRevenueRepositoryProtocol) -> None:
        self.repository = repository

    def options(self, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.options(actor=actor)

    def create(self, quotation: SalesQuotation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.create(quotation, command_id=command_id, actor=actor)

    def get(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.get(identifier, actor=actor)

    def list(self, *, actor: PostingActor, after: str = "") -> dict[str, Any]:
        return self.repository.list(actor=actor, after=after)

    def transition(
        self,
        identifier: str,
        *,
        operation: str,
        expected_version: int,
        reason: str,
        command_id: str,
        actor: PostingActor,
        reference: str = "",
        business_date: str = "",
    ) -> dict[str, Any]:
        return self.repository.transition(
            identifier,
            operation=operation,
            expected_version=expected_version,
            reason=reason,
            command_id=command_id,
            actor=actor,
            reference=reference,
            business_date=business_date,
        )

    def prepare_invoice(
        self,
        identifier: str,
        preparation: SalesInvoicePreparation,
        *,
        expected_version: int,
        command_id: str,
        actor: PostingActor,
    ) -> dict[str, Any]:
        return self.repository.prepare_invoice(
            identifier, preparation, expected_version=expected_version, command_id=command_id, actor=actor
        )

    def review_invoice(
        self, identifier: str, *, expected_version: int, command_id: str, reason: str, actor: PostingActor
    ) -> dict[str, Any]:
        return self.repository.review_invoice(
            identifier, expected_version=expected_version, command_id=command_id, reason=reason, actor=actor
        )

    def post_invoice(
        self, identifier: str, *, expected_version: int, command_id: str, reason: str, actor: PostingActor
    ) -> dict[str, Any]:
        return self.repository.post_invoice(
            identifier, expected_version=expected_version, command_id=command_id, reason=reason, actor=actor
        )

    def prepare_collection(
        self,
        identifier: str,
        *,
        expected_version: int,
        command_id: str,
        reason: str,
        actor: PostingActor,
        receipt_number: str,
        receipt_date: str,
        journal_code: str,
        period_id: str,
        cash_account_code: str,
    ) -> dict[str, Any]:
        return self.repository.prepare_collection(
            identifier,
            expected_version=expected_version,
            command_id=command_id,
            reason=reason,
            actor=actor,
            receipt_number=receipt_number,
            receipt_date=receipt_date,
            journal_code=journal_code,
            period_id=period_id,
            cash_account_code=cash_account_code,
        )

    def review_collection(
        self, identifier: str, *, expected_version: int, command_id: str, reason: str, actor: PostingActor
    ) -> dict[str, Any]:
        return self.repository.review_collection(
            identifier, expected_version=expected_version, command_id=command_id, reason=reason, actor=actor
        )

    def post_collection(
        self, identifier: str, *, expected_version: int, command_id: str, reason: str, actor: PostingActor
    ) -> dict[str, Any]:
        return self.repository.post_collection(
            identifier, expected_version=expected_version, command_id=command_id, reason=reason, actor=actor
        )
