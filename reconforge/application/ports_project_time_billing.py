"""The project billing source reuses the existing AR and native GL engines."""

from typing import Any, Protocol

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.people_project_payroll import PeopleScope
from reconforge.domain.project_time_billing import ProjectPriceAgreement


class ProjectTimeBillingRepository(Protocol):
    def register_price(
        self, request: ProjectPriceAgreement, *, command_id: str, actor: PostingActor
    ) -> dict[str, Any]: ...
    def approve_price(
        self, price_id: str, *, expected_digest: str, command_id: str, actor: PostingActor
    ) -> dict[str, Any]: ...
    def prepare_invoice(
        self,
        scope: PeopleScope,
        *,
        time_ids: list[str],
        price_ids: list[str],
        customer_code: str,
        invoice_number: str,
        period_id: str,
        posting_date: str,
        due_date: str,
        journal_code: str,
        receivable_account_code: str,
        revenue_account_code: str,
        cash_account_code: str,
        command_id: str,
        actor: PostingActor,
    ) -> dict[str, Any]: ...
    def prepare_collection(
        self,
        invoice_id: str,
        *,
        amount_minor: int,
        period_id: str,
        posting_date: str,
        command_id: str,
        actor: PostingActor,
    ) -> dict[str, Any]: ...
    def review(
        self, plan_id: str, *, expected_plan_digest: str, command_id: str, actor: PostingActor
    ) -> dict[str, Any]: ...
    def post(
        self, plan_id: str, *, expected_plan_digest: str, command_id: str, actor: PostingActor
    ) -> dict[str, Any]: ...
    def cancel(
        self, invoice_id: str, *, expected_plan_digest: str, command_id: str, actor: PostingActor
    ) -> dict[str, Any]: ...
    def get(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def evidence(self, invoice_id: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def catalog(
        self, scope: PeopleScope, *, after: str = "", limit: int = 25, actor: PostingActor
    ) -> dict[str, Any]: ...
