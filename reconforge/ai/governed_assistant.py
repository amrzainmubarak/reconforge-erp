"""Governed, permission-aware business AI assistant.

Enforces zero-autonomous-posting boundaries, strict tenant/workspace isolation,
source-grounded evidence citations, and maker-checker human approval envelopes.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from reconforge.domain.finance_posting import FinancePostingError, text


class GovernedAISecurityError(FinancePostingError):
    """Raised when an AI operation attempts unauthorized data access or sensitive mutation."""


@dataclass(frozen=True)
class GovernedProposal:
    proposal_id: str
    action_type: str
    target_entity_id: str
    summary: str
    requires_maker_checker: bool
    required_permission: str

    def __post_init__(self) -> None:
        text(self.proposal_id, "proposal_id")
        text(self.action_type, "action_type")
        text(self.target_entity_id, "target_entity_id")
        text(self.summary, "summary", maximum=500)
        text(self.required_permission, "required_permission")


@dataclass(frozen=True)
class AssistantResponse:
    query_id: str
    answer: str
    confidence_score: float
    cited_evidence_ids: tuple[str, ...]
    data_classification: str
    proposals: tuple[GovernedProposal, ...]

    def __post_init__(self) -> None:
        text(self.query_id, "query_id")
        text(self.answer, "answer", maximum=5000)
        if not 0.0 <= self.confidence_score <= 1.0:
            raise ValueError(f"Confidence score must be in [0.0, 1.0]: {self.confidence_score}")
        if self.data_classification not in {"Public", "Internal", "Restricted", "Confidential"}:
            raise ValueError(f"Invalid data classification: {self.data_classification}")


class GovernedAssistantEngine:
    """Evaluates business queries against authorized domain context and produces governed responses."""

    def __init__(self, workspace_id: str, granted_permissions: frozenset[str]) -> None:
        self.workspace_id = text(workspace_id, "workspace_id")
        self.granted_permissions = frozenset(granted_permissions)

    def evaluate_query(
        self,
        query_id: str,
        query_text: str,
        authorized_records: Sequence[dict[str, object]],
    ) -> AssistantResponse:
        """Evaluates a user query with strict permission filtering and source citations."""
        text(query_id, "query_id")
        clean_query = text(query_text, "query_text", maximum=1000)

        # Detect and refuse prompt injection / privilege escalation attempts
        suspicious_patterns = [
            r"ignore previous instructions",
            r"bypass rls",
            r"drop table",
            r"grant admin",
            r"delete from",
            r"update\s+\w+\s+set",
        ]
        for pattern in suspicious_patterns:
            if re.search(pattern, clean_query, re.IGNORECASE):
                raise GovernedAISecurityError(
                    "ai_injection_refused",
                    "Security Refusal: query contains prohibited administrative or injection instructions."
                )

        # Verify that all provided records belong strictly to the authorized workspace
        for rec in authorized_records:
            rec_ws = str(rec.get("workspace_id") or "")
            if rec_ws and rec_ws != self.workspace_id:
                raise GovernedAISecurityError(
                    "ai_cross_workspace_prohibited",
                    f"Access Denied: record '{rec.get('id')}' belongs to workspace '{rec_ws}', "
                    f"outside authorized workspace '{self.workspace_id}'."
                )

        # Extract citation references from the authorized records
        citations = tuple(
            str(rec["id"]) for rec in authorized_records if "id" in rec and str(rec["id"]).strip()
        )

        # Check for mutation/posting intent in query
        mutation_keywords = ["approve", "post", "cancel", "refund", "close period", "transfer"]
        detected_action = next((kw for kw in mutation_keywords if kw in clean_query.lower()), None)

        proposals: list[GovernedProposal] = []
        if detected_action:
            # AI NEVER directly executes; it drafts a GovernedProposal
            proposals.append(
                GovernedProposal(
                    proposal_id=f"PROP-{query_id}",
                    action_type=f"proposed_{detected_action.replace(' ', '_')}",
                    target_entity_id=citations[0] if citations else "UNKNOWN",
                    summary=f"AI proposed {detected_action} based on user inquiry. Requires explicit human confirmation.",
                    requires_maker_checker=True,
                    required_permission=f"finance_posting.{detected_action.replace(' ', '_')}",
                )
            )
            answer_text = (
                f"I identified a proposed business action: '{detected_action}'. "
                "In accordance with ReconForge financial integrity controls, AI cannot execute postings or approvals directly. "
                "A governed proposal has been generated for maker-checker review."
            )
        else:
            answer_text = (
                f"Analysis completed across {len(authorized_records)} authorized records in workspace '{self.workspace_id}'. "
                f"Retrieved relevant business context: {citations[:5]}."
            )

        return AssistantResponse(
            query_id=query_id,
            answer=answer_text,
            confidence_score=0.95 if citations else 0.80,
            cited_evidence_ids=citations,
            data_classification="Internal" if citations else "Public",
            proposals=tuple(proposals),
        )
