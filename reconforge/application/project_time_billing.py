"""Closed billing commands; the native source owner retains all transactions."""

import re
from dataclasses import dataclass
from typing import Any, Literal

from reconforge.application.ports_project_time_billing import ProjectTimeBillingRepository
from reconforge.domain.finance_posting import PostingActor, text
from reconforge.domain.project_time_billing import fail


@dataclass(frozen=True)
class ProjectTimeBillingService:
    repository: ProjectTimeBillingRepository

    def financial_phase(
        self,
        action: Literal["review", "post", "cancel"],
        plan_id: str,
        *,
        expected_plan_digest: str,
        command_id: str,
        actor: PostingActor,
    ) -> dict[str, Any]:
        text(command_id, "Command ID", maximum=140)
        if text(plan_id, "Original project billing source") != plan_id or not plan_id.startswith(("PB1-", "PB1C-")):
            fail("Financial command requires its original project billing source.")
        if not isinstance(expected_plan_digest, str) or re.fullmatch(r"[a-f0-9]{64}", expected_plan_digest) is None:
            fail("Financial phase requires the exact original source digest.")
        if action == "cancel" and not plan_id.startswith("PB1-"):
            fail("Only an unposted invoice may release billing claims in this contract.")
        operations = {"review": self.repository.review, "post": self.repository.post, "cancel": self.repository.cancel}
        if action not in operations:
            fail("Unknown project billing financial command.")
        return operations[action](
            plan_id, expected_plan_digest=expected_plan_digest, command_id=command_id, actor=actor
        )
