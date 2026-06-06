"""RBAC and separation-of-duties primitives."""

from __future__ import annotations

from dataclasses import dataclass

CONFLICTING_ACTIONS: dict[str, set[str]] = {
    "prepare": {"review", "approve"},
    "review": {"prepare"},
    "submit": {"approve"},
    "approve": {"prepare", "submit"},
}


@dataclass(frozen=True)
class SoDCheckResult:
    """Result of a separation-of-duties check."""

    allowed: bool
    reason: str = ""


def required_permission_for_action(object_type: str, action: str) -> str:
    """Return the conventional permission name for an object/action pair."""

    return f"{object_type}.{action}"


def has_permission(user_permissions: set[str], permission: str) -> bool:
    """Return whether a permission set contains an exact permission."""

    return permission in user_permissions


def check_object_action_permission(user_permissions: set[str], object_type: str, action: str) -> bool:
    """Check the conventional object/action permission name."""

    return has_permission(user_permissions, required_permission_for_action(object_type, action))


def check_sod_conflict(
    *,
    user_id: str,
    object_type: str,
    object_id: str,
    action: str,
    prior_actions: list[tuple[str, str, str, str]],
) -> SoDCheckResult:
    """Prevent the same user from performing conflicting duties on the same object."""

    normalized_action = action.strip().lower()
    conflicts = CONFLICTING_ACTIONS.get(normalized_action, set())
    for prior_user_id, prior_object_type, prior_object_id, prior_action in prior_actions:
        if prior_user_id != user_id or prior_object_type != object_type or prior_object_id != object_id:
            continue
        normalized_prior = prior_action.strip().lower()
        if normalized_prior in conflicts:
            return SoDCheckResult(
                allowed=False,
                reason=f"Separation of duties conflict: same user cannot {normalized_action} after {normalized_prior}.",
            )
    return SoDCheckResult(allowed=True)
