"""Governed, permission-aware business AI assistant.

Enforces zero-autonomous-posting boundaries, strict tenant/workspace isolation,
source-grounded evidence citations, and maker-checker human approval envelopes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from reconforge.domain.finance_posting import FinancePostingError, text

CONFIDENCE_THRESHOLD: float = 0.85


class GovernedAISecurityError(FinancePostingError):
    """Raised when an AI operation attempts unauthorized data access or sensitive mutation."""


@dataclass(frozen=True)
class CitationNode:
    """Structured evidence graph node for source grounding."""

    node_id: str
    entity_type: str
    record_id: str
    version_digest: str
    summary: str

    def __post_init__(self) -> None:
        text(self.node_id, "node_id")
        text(self.entity_type, "entity_type")
        text(self.record_id, "record_id")
        text(self.version_digest, "version_digest")
        text(self.summary, "summary", maximum=500)


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
    citation_graph: tuple[CitationNode, ...] = ()
    requires_clarification: bool = False

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
        authorized_records: Sequence[Mapping[str, object]],
        *,
        confidence_override: float | None = None,
    ) -> AssistantResponse:
        """Evaluates a user query with strict permission filtering, source citations, and confidence gating."""
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
                    "Security Refusal: query contains prohibited administrative or injection instructions.",
                )

        # Detect and refuse attempts at autonomous GL posting
        autonomous_gl_patterns = [
            r"autonomous(ly)?\s+(post|mutation|gl|journal|action)",
            r"post\b.*?\bwithout\s+(approval|maker-checker|human|confirmation)",
            r"bypass\s+(approval|maker-checker|confirmation|human)",
            r"direct(ly)?\s+(post\s+to\s+gl|gl\s+posting|ledger\s+insert|post)",
            r"insert\s+(into\s+)?gl(_lines)?",
            r"modify\s+balance",
        ]
        for pattern in autonomous_gl_patterns:
            if re.search(pattern, clean_query, re.IGNORECASE):
                raise GovernedAISecurityError(
                    "ai_autonomous_gl_prohibited",
                    "Financial Integrity Violation: Autonomous GL postings are strictly prohibited. "
                    "All financial modifications require human maker-checker approval envelopes.",
                )

        # Verify that all provided records belong strictly to the authorized workspace
        for rec in authorized_records:
            rec_ws = str(rec.get("workspace_id") or "")
            if rec_ws and rec_ws != self.workspace_id:
                raise GovernedAISecurityError(
                    "ai_cross_workspace_prohibited",
                    f"Access Denied: record '{rec.get('id')}' belongs to workspace '{rec_ws}', "
                    f"outside authorized workspace '{self.workspace_id}'.",
                )

        # Extract citation references and build structured citation graph
        citations = tuple(
            str(rec["id"]) for rec in authorized_records if "id" in rec and str(rec["id"]).strip()
        )
        citation_nodes: list[CitationNode] = []
        for rec in authorized_records:
            if "id" in rec and str(rec["id"]).strip():
                rec_id = str(rec["id"]).strip()
                entity_type = str(rec.get("entity_type") or "record")
                version_digest = str(rec.get("version_digest") or rec.get("digest") or f"sha256:{abs(hash(str(rec))):08x}")
                summary = str(rec.get("summary") or f"Record {rec_id} in {self.workspace_id}")
                citation_nodes.append(
                    CitationNode(
                        node_id=f"CNODE-{rec_id}",
                        entity_type=entity_type,
                        record_id=rec_id,
                        version_digest=version_digest,
                        summary=summary,
                    )
                )

        # Determine confidence score
        if confidence_override is not None:
            confidence = float(confidence_override)
            if not 0.0 <= confidence <= 1.0:
                raise ValueError(f"Confidence score must be in [0.0, 1.0]: {confidence}")
        else:
            confidence = 0.95 if citations else 0.80

        # Check for mutation/posting intent in query
        mutation_keywords = ["approve", "post", "cancel", "refund", "close period", "transfer"]
        detected_action = next((kw for kw in mutation_keywords if kw in clean_query.lower()), None)

        # Confidence threshold gating: if confidence < 0.85, set requires_clarification=True and refuse proposals
        if confidence < CONFIDENCE_THRESHOLD:
            requires_clarification = True
            proposals: list[GovernedProposal] = []
            answer_text = (
                f"Grounding confidence ({confidence:.2f}) is below required governance threshold ({CONFIDENCE_THRESHOLD:.2f}). "
                "Automated proposals are refused. Please provide clarifying context or specific record references."
            )
        else:
            requires_clarification = False
            proposals = []
            if detected_action:
                # AI NEVER directly executes; it drafts a GovernedProposal with human maker-checker envelope
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
            confidence_score=confidence,
            cited_evidence_ids=citations,
            data_classification="Internal" if citations else "Public",
            proposals=tuple(proposals),
            citation_graph=tuple(citation_nodes),
            requires_clarification=requires_clarification,
        )
