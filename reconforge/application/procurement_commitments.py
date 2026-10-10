"""One appropriation owner; native budgets, inventory, AP and GL remain authoritative."""
from typing import Any, Protocol

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.procurement_commitments import BudgetPurchasePreparation


class ProcurementCommitmentRepository(Protocol):
    def create(self, request: BudgetPurchasePreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def get(self, order_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def consume_invoice(self, order_id: str, invoice_id: str, *, expected_order_version: int,
                        expected_budget_version: int, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]: ...
    def release(self, order_id: str, *, expected_order_version: int, expected_budget_version: int,
                posting_date: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]: ...
