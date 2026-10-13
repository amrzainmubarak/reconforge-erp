"""Use-case facade; transactions remain with the existing native owner."""
import re
from dataclasses import dataclass
from typing import Any, Literal

from reconforge.application.ports_people_project_payroll import PeopleProjectPayrollRepository
from reconforge.domain.finance_posting import PostingActor, text
from reconforge.domain.people_project_payroll import fail


@dataclass(frozen=True)
class PeopleProjectPayrollService:
    repository: PeopleProjectPayrollRepository

    def financial_phase(self, action: Literal["review", "post", "cancel"], plan_id: str, *,
                        expected_plan_digest: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        """Admit a closed, versioned command; native owner retains the transaction.

        Cancellation is deliberately limited to unposted accruals. A future
        posted correction requires a separate source-owned correction contract.
        """
        text(command_id, "Command ID", maximum=140)
        text(plan_id, "Original workforce source")
        if not re.fullmatch(r"[a-f0-9]{64}", expected_plan_digest):
            fail("Financial phase requires the exact original source digest.")
        if action == "cancel" and not plan_id.startswith("HC1-"):
            fail("Only an unposted accrual can cancel in this contract.")
        operations = {"review": self.repository.review, "post": self.repository.post, "cancel": self.repository.cancel}
        if action not in operations:
            fail("Unknown workforce financial command.")
        return operations[action](plan_id, expected_plan_digest=expected_plan_digest, command_id=command_id, actor=actor)

