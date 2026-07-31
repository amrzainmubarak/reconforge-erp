"""Safe, backend-neutral contracts for consolidated PostgreSQL audit browsing.

The platform has two append-only audit chains during the strangler migration:
the ledger-control chain and the domain chain.  They remain independently
verifiable; this module only gives authorized administrators a deterministic,
redacted read model across both sources.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

AuditSource = Literal["domain", "ledger_control"]


class AuditBrowsingError(ValueError):
    """Raised for a bounded, safe audit-browsing request failure."""


@dataclass(frozen=True)
class RedactedAuditEvent:
    """One audit event without raw subject, object, reason, or metadata text."""

    source: AuditSource
    event_id: str
    sequence: int
    occurred_at: str
    action: str
    object_type: str
    actor_digest: str
    object_digest: str
    metadata_digest: str
    previous_event_hash: str
    event_hash: str
    before_state_hash: str | None
    after_state_hash: str | None


@dataclass(frozen=True)
class AuditChainVerification:
    """Safe verification summary for one independent tenant audit chain."""

    source: AuditSource
    ok: bool
    checked_events: int
    head_hash: str
    issue_codes: tuple[str, ...]


@dataclass(frozen=True)
class AuditVerificationSummary:
    """The two chain results and a conservative overall result."""

    ok: bool
    chains: tuple[AuditChainVerification, ...]


class AuditBrowsingRepositoryProtocol(Protocol):
    """A tenant-scoped, persistence-neutral audit browsing boundary."""

    def list_redacted_events(
        self,
        *,
        limit: int,
        after_occurred_at: str | None = None,
        after_source: AuditSource | None = None,
        after_event_id: str | None = None,
    ) -> tuple[RedactedAuditEvent, ...]: ...

    def verify_chains(self) -> AuditVerificationSummary: ...


@dataclass(frozen=True)
class AuditBrowsePage:
    """A stable page plus the final event used to construct a signed cursor."""

    events: tuple[RedactedAuditEvent, ...]
    has_more: bool


class AuditBrowsingApplicationService:
    """Validate and bound a consolidated audit-browsing operation."""

    def __init__(self, repository: AuditBrowsingRepositoryProtocol) -> None:
        self._repository = repository

    def list_events(
        self,
        *,
        limit: int,
        after_occurred_at: str | None = None,
        after_source: AuditSource | None = None,
        after_event_id: str | None = None,
    ) -> AuditBrowsePage:
        if isinstance(limit, bool) or not 1 <= limit <= 200:
            raise AuditBrowsingError("Audit page limit must be between 1 and 200.")
        continuation = (after_occurred_at, after_source, after_event_id)
        if any(value is not None for value in continuation) and not all(value is not None for value in continuation):
            raise AuditBrowsingError("Audit cursor continuation is incomplete.")
        if after_source is not None and after_source not in {"domain", "ledger_control"}:
            raise AuditBrowsingError("Audit cursor source is invalid.")
        records = self._repository.list_redacted_events(
            limit=limit + 1,
            after_occurred_at=after_occurred_at,
            after_source=after_source,
            after_event_id=after_event_id,
        )
        return AuditBrowsePage(events=records[:limit], has_more=len(records) > limit)

    def verify(self) -> AuditVerificationSummary:
        result = self._repository.verify_chains()
        sources = {chain.source for chain in result.chains}
        if sources != {"domain", "ledger_control"}:
            raise AuditBrowsingError("Audit verification did not return both required chains.")
        return result
