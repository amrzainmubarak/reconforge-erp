"""Backend-neutral application boundary for evidence-bound AP settlement.

The financial-posting module remains the owner of journal construction,
independent review, and posting.  This use case only records that an already
posted, exact AP/cash effect settles an approved supplier invoice.
"""

from __future__ import annotations

from typing import Any, Protocol


class PayablesPaymentLinkRepositoryProtocol(Protocol):
    """Persistence port for one immutable supplier-invoice payment allocation."""

    def link_finance_payment(
        self,
        invoice_id: str,
        *,
        finance_effect_id: str,
        ap_account_id: str,
        cash_account_id: str,
        expected_invoice_version: int,
        command_id: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def list_payment_links(self, invoice_id: str, *, actor_label: str = "local-cli") -> list[dict[str, Any]]: ...


class PayablesPaymentLinkApplicationService:
    """Coordinate AP settlement linkage without owning database transactions."""

    def __init__(self, repository: PayablesPaymentLinkRepositoryProtocol) -> None:
        self.repository = repository

    def link_finance_payment(
        self,
        invoice_id: str,
        *,
        finance_effect_id: str,
        ap_account_id: str,
        cash_account_id: str,
        expected_invoice_version: int,
        command_id: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.link_finance_payment(
            invoice_id,
            finance_effect_id=finance_effect_id,
            ap_account_id=ap_account_id,
            cash_account_id=cash_account_id,
            expected_invoice_version=expected_invoice_version,
            command_id=command_id,
            actor_label=actor_label,
        )

    def list_payment_links(self, invoice_id: str, *, actor_label: str = "local-cli") -> list[dict[str, Any]]:
        return self.repository.list_payment_links(invoice_id, actor_label=actor_label)


__all__ = ["PayablesPaymentLinkApplicationService", "PayablesPaymentLinkRepositoryProtocol"]
