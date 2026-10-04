"""Pure invariants for the PostgreSQL exception-review boundary.

The local exception queue keeps its historical, permissive compatibility
surface.  Server review is a separate governed boundary: callers supply an
optimistic version, follow a small explicit workflow, and cannot make a
review decision for an exception they created.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

EXCEPTION_REVIEW_STATUSES = frozenset({"Open", "In Review", "Resolved", "Accepted Risk", "Closed"})
EXCEPTION_REVIEW_RISK_RATINGS = frozenset({"low", "medium", "high", "critical"})
EXCEPTION_REVIEW_DECISION_STATUSES = frozenset({"Resolved", "Accepted Risk", "Closed"})
EXCEPTION_REVIEW_TRANSITIONS: dict[str, frozenset[str]] = {
    "Open": frozenset({"In Review"}),
    "In Review": frozenset({"Resolved", "Accepted Risk"}),
    "Resolved": frozenset({"Closed"}),
    "Accepted Risk": frozenset({"Closed"}),
    "Closed": frozenset(),
}


class ExceptionReviewError(ValueError):
    """Base class for safe exception-review validation failures."""


class ExceptionReviewConflictError(ExceptionReviewError):
    """Raised when a stale version or workflow state cannot be applied."""


class ExceptionReviewNotFoundError(ExceptionReviewError):
    """Raised when an exception is absent from the authorized review scope."""


class ExceptionReviewSeparationError(ExceptionReviewError):
    """Raised when an actor would review an exception they created."""


class ExceptionReviewCreatorIdentityError(ExceptionReviewSeparationError):
    """Raised when a legacy record cannot prove the immutable creator identity."""


class ExceptionReviewReviewerError(ExceptionReviewError):
    """Raised when a nominated reviewer is not eligible for the governed scope."""


class ExceptionReviewAssigneeError(ExceptionReviewConflictError):
    """Raised when a review decision is not made by the assigned reviewer."""


def _required(value: object, field: str, maximum: int = 200) -> str:
    result = str(value or "").strip()
    if not result:
        raise ExceptionReviewError(f"{field} is required.")
    if len(result) > maximum:
        raise ExceptionReviewError(f"{field} must not exceed {maximum} characters.")
    if any(ord(character) < 32 or ord(character) == 127 for character in result):
        raise ExceptionReviewError(f"{field} must contain printable characters only.")
    return result


def _optional(value: object, field: str, maximum: int = 200) -> str | None:
    if value is None or not str(value).strip():
        return None
    return _required(value, field, maximum)


def _same_actor_id(left: object, right: object) -> bool:
    """Compare immutable identity identifiers without label normalization."""

    left_value = str(left or "").strip()
    right_value = str(right or "").strip()
    return bool(left_value and right_value and left_value == right_value)


def _record_text(record: Mapping[str, object], field: str) -> str:
    return str(record.get(field) or "").strip()


def _record_version(record: Mapping[str, object]) -> int:
    value = record.get("row_version")
    if type(value) is not int or value < 1:
        raise ExceptionReviewError("Exception review record has an invalid version.")
    return value


def _creator_actor_id(record: Mapping[str, object]) -> str:
    """Return persisted creator identity or fail closed for legacy labels.

    ``created_by`` is retained for compatibility and presentation only.  It can
    change independently of an account identity, so a governed assignment or
    terminal review decision is unavailable until migration or intake persists
    ``created_by_actor_id``.
    """

    creator = _record_text(record, "created_by_actor_id")
    if not creator:
        raise ExceptionReviewCreatorIdentityError(
            "Exception creator identity is unavailable; governed review requires an immutable creator identity."
        )
    return creator


@dataclass(frozen=True)
class ExceptionReviewScope:
    """Authenticated hierarchy applied to every server review operation."""

    tenant_id: str
    workspace_id: str
    organization_id: str | None = None
    legal_entity_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _required(self.tenant_id, "Tenant id", 160))
        object.__setattr__(self, "workspace_id", _required(self.workspace_id, "Workspace id", 160))
        object.__setattr__(self, "organization_id", _optional(self.organization_id, "Organization id", 160))
        object.__setattr__(self, "legal_entity_id", _optional(self.legal_entity_id, "Legal entity id", 160))
        if self.legal_entity_id is not None and self.organization_id is None:
            raise ExceptionReviewError("Legal-entity scope requires organization scope.")


@dataclass(frozen=True)
class ExceptionReviewQuery:
    """Bounded filters for a server review list."""

    period_name: str = ""
    entity_code: str = ""
    account_code: str = ""
    control_code: str = ""
    risk_rating: str = ""
    owner: str = ""
    status: str = ""

    def __post_init__(self) -> None:
        for name, maximum in (
            ("period_name", 64),
            ("entity_code", 160),
            ("account_code", 160),
            ("control_code", 160),
            ("risk_rating", 32),
            ("owner", 160),
            ("status", 32),
        ):
            value = str(getattr(self, name) or "").strip()
            if len(value) > maximum:
                raise ExceptionReviewError(f"{name.replace('_', ' ').capitalize()} must not exceed {maximum} characters.")
            object.__setattr__(self, name, value)
        if self.risk_rating and self.risk_rating not in EXCEPTION_REVIEW_RISK_RATINGS:
            raise ExceptionReviewError("Risk rating is invalid for governed review.")
        if self.status and self.status not in EXCEPTION_REVIEW_STATUSES:
            raise ExceptionReviewError("Exception status is invalid for governed review.")


@dataclass(frozen=True)
class ExceptionReviewHistoryPage:
    """A bounded, cursor-based history page for retained review evidence."""

    limit: int = 100
    cursor: str | None = None

    def __post_init__(self) -> None:
        if type(self.limit) is not int or not 1 <= self.limit <= 250:
            raise ExceptionReviewError("History limit must be an integer from 1 through 250.")
        object.__setattr__(self, "cursor", _optional(self.cursor, "History cursor", 200))


@dataclass(frozen=True)
class ExceptionReviewListPage:
    """A bounded, cursor-based page for the governed exception list."""

    limit: int = 100
    cursor: str | None = None

    def __post_init__(self) -> None:
        if type(self.limit) is not int or not 1 <= self.limit <= 250:
            raise ExceptionReviewError("List limit must be an integer from 1 through 250.")
        object.__setattr__(self, "cursor", _optional(self.cursor, "List cursor", 200))


@dataclass(frozen=True)
class ExceptionReviewAssignment:
    """One version-bound assignment made by an authenticated actor."""

    exception_id: str
    owner: str
    expected_version: int
    actor_id: str
    actor_label: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "exception_id", _required(self.exception_id, "Exception id", 200))
        object.__setattr__(self, "owner", _required(self.owner, "Exception owner", 160))
        if type(self.expected_version) is not int or self.expected_version < 1:
            raise ExceptionReviewError("Expected version must be a positive integer.")
        object.__setattr__(self, "actor_id", _required(self.actor_id, "Actor id", 160))
        object.__setattr__(self, "actor_label", _required(self.actor_label, "Actor label", 160))

    def validate_record(self, record: Mapping[str, object]) -> None:
        if _record_version(record) != self.expected_version:
            raise ExceptionReviewConflictError("Exception review was changed by another request.")
        if _record_text(record, "status") == "Closed":
            raise ExceptionReviewConflictError("Closed exception cannot be reassigned.")
        creator = _creator_actor_id(record)
        if _same_actor_id(self.owner, creator):
            raise ExceptionReviewSeparationError("Exception creator cannot be assigned as its reviewer.")


@dataclass(frozen=True)
class ExceptionReviewTransition:
    """One version-bound status decision with retained reason evidence."""

    exception_id: str
    status: str
    expected_version: int
    actor_id: str
    actor_label: str
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "exception_id", _required(self.exception_id, "Exception id", 200))
        selected_status = _required(self.status, "Exception status", 32)
        if selected_status not in EXCEPTION_REVIEW_STATUSES:
            raise ExceptionReviewError("Exception status is invalid for governed review.")
        object.__setattr__(self, "status", selected_status)
        if type(self.expected_version) is not int or self.expected_version < 1:
            raise ExceptionReviewError("Expected version must be a positive integer.")
        object.__setattr__(self, "actor_id", _required(self.actor_id, "Actor id", 160))
        object.__setattr__(self, "actor_label", _required(self.actor_label, "Actor label", 160))
        reason = str(self.reason or "").strip()
        if len(reason) > 1_000:
            raise ExceptionReviewError("Review reason must not exceed 1000 characters.")
        if any(ord(character) < 32 or ord(character) == 127 for character in reason):
            raise ExceptionReviewError("Review reason must contain printable characters only.")
        object.__setattr__(self, "reason", reason)

    def validate_record(self, record: Mapping[str, object]) -> None:
        if _record_version(record) != self.expected_version:
            raise ExceptionReviewConflictError("Exception review was changed by another request.")
        current_status = _record_text(record, "status")
        allowed = EXCEPTION_REVIEW_TRANSITIONS.get(current_status)
        if allowed is None or self.status not in allowed:
            raise ExceptionReviewConflictError(
                f"Invalid governed exception transition: {current_status or 'unknown'} -> {self.status}."
            )
        if self.status == "Accepted Risk" and not self.reason:
            raise ExceptionReviewError("Accepted Risk requires a review reason.")
        if self.status not in EXCEPTION_REVIEW_DECISION_STATUSES:
            return
        creator = _creator_actor_id(record)
        if _same_actor_id(self.actor_id, creator):
            raise ExceptionReviewSeparationError("Exception creator cannot make its review decision.")
        assigned_reviewer = _record_text(record, "owner")
        if not _same_actor_id(self.actor_id, assigned_reviewer):
            raise ExceptionReviewAssigneeError("A terminal review decision requires the assigned reviewer.")


__all__ = [
    "EXCEPTION_REVIEW_DECISION_STATUSES",
    "EXCEPTION_REVIEW_RISK_RATINGS",
    "EXCEPTION_REVIEW_STATUSES",
    "EXCEPTION_REVIEW_TRANSITIONS",
    "ExceptionReviewAssigneeError",
    "ExceptionReviewAssignment",
    "ExceptionReviewConflictError",
    "ExceptionReviewCreatorIdentityError",
    "ExceptionReviewError",
    "ExceptionReviewHistoryPage",
    "ExceptionReviewListPage",
    "ExceptionReviewNotFoundError",
    "ExceptionReviewQuery",
    "ExceptionReviewReviewerError",
    "ExceptionReviewScope",
    "ExceptionReviewSeparationError",
    "ExceptionReviewTransition",
]
