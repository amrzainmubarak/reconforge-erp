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


def same_actor(left: object, right: object) -> bool:
    """Compare two non-empty actor identities with one canonical policy."""

    left_text = str(left or "").strip().casefold()
    right_text = str(right or "").strip().casefold()
    return bool(left_text and right_text and left_text == right_text)


def canonical_policy_value(value: object) -> str:
    """Normalize persisted policy identifiers and actions for comparisons.

    Policy decisions must not depend on presentation casing or accidental
    surrounding whitespace.  Empty values remain empty so missing identity
    continues to fail closed.
    """

    return str(value or "").strip().casefold()


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

    normalized_user_id = canonical_policy_value(user_id)
    normalized_object_type = canonical_policy_value(object_type)
    normalized_object_id = canonical_policy_value(object_id)
    normalized_action = canonical_policy_value(action)
    conflicts = CONFLICTING_ACTIONS.get(normalized_action, set())
    for prior_user_id, prior_object_type, prior_object_id, prior_action in prior_actions:
        if (
            canonical_policy_value(prior_user_id) != normalized_user_id
            or canonical_policy_value(prior_object_type) != normalized_object_type
            or canonical_policy_value(prior_object_id) != normalized_object_id
        ):
            continue
        normalized_prior = canonical_policy_value(prior_action)
        if normalized_prior in conflicts:
            return SoDCheckResult(
                allowed=False,
                reason=f"Separation of duties conflict: same user cannot {normalized_action} after {normalized_prior}.",
            )
    return SoDCheckResult(allowed=True)
