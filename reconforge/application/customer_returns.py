"""Complete native source-owner contract, independent of HTTP and Studio."""

from typing import Any, Protocol

from reconforge.domain.customer_returns import CustomerRefundPreparation, CustomerReturnPreparation
from reconforge.domain.finance_posting import PostingActor


class CustomerReturnsRepository(Protocol):
    def prepare(self, request: CustomerReturnPreparation, *, command_id: str,
                actor: PostingActor) -> dict[str, Any]: ...
    def prepare_refund(self, request: CustomerRefundPreparation, *, command_id: str,
                       actor: PostingActor) -> dict[str, Any]: ...
    def get(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def review(self, plan_id: str, *, expected_plan_digest: str, command_id: str,
               reason: str, actor: PostingActor) -> dict[str, Any]: ...
    def post(self, plan_id: str, *, expected_plan_digest: str, command_id: str,
             reason: str, actor: PostingActor) -> dict[str, Any]: ...
    def cancel(self, plan_id: str, *, expected_plan_digest: str, command_id: str,
               reason: str, actor: PostingActor) -> dict[str, Any]: ...
