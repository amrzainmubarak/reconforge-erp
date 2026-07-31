from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reconforge.application.identity_administration import (
    IdentityAdministrationApplicationService,
    IdentityAdministrationError,
    IdentitySessionPage,
    IdentitySessionSummary,
    IdentityUserPage,
    IdentityUserSummary,
    SessionRevocation,
    UserStatusChange,
)

NOW = datetime(2026, 7, 29, 20, 0, tzinfo=UTC)


def _user(*, disabled: bool = False, version: int = 1) -> IdentityUserSummary:
    return IdentityUserSummary(
        id="user-a",
        username="admin-a",
        display_name="Admin A",
        disabled=disabled,
        lifecycle_version=version,
        roles=("administrator",),
        active_sessions=0 if disabled else 1,
        created_at="2026-07-29T19:00:00Z",
        disabled_at="2026-07-29T20:00:00Z" if disabled else None,
        state_digest="a" * 64,
    )


def _session(*, version: int = 1) -> IdentitySessionSummary:
    return IdentitySessionSummary(
        id="session-a",
        user_id="user-a",
        username="admin-a",
        status="active",
        lifecycle_version=version,
        created_at="2026-07-29T19:00:00Z",
        expires_at="2026-07-29T21:00:00Z",
        last_used_at=None,
        revoked_at=None,
        revocation_reason_code=None,
        client_ip_recorded=True,
        user_agent_recorded=True,
        state_digest="b" * 64,
    )


class _Repository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def list_users(self, **kwargs: object) -> IdentityUserPage:
        self.calls.append(("list_users", kwargs))
        return IdentityUserPage((_user(),))

    def set_user_disabled(self, **kwargs: object) -> UserStatusChange:
        self.calls.append(("set_user_disabled", kwargs))
        return UserStatusChange(_user(disabled=bool(kwargs["disabled"]), version=2), True, 1, "audit-a")

    def list_sessions(self, **kwargs: object) -> IdentitySessionPage:
        self.calls.append(("list_sessions", kwargs))
        return IdentitySessionPage((_session(),))

    def revoke_session(self, **kwargs: object) -> SessionRevocation:
        self.calls.append(("revoke_session", kwargs))
        return SessionRevocation(_session(version=2), True, False, "audit-b")


def test_application_contract_normalizes_scope_and_forwards_whole_second_clock() -> None:
    repository = _Repository()
    service = IdentityAdministrationApplicationService(repository, clock=lambda: NOW)

    assert service.list_users(limit=10, after_username=" Admin-A ", after_user_id=" USER-A ").items
    changed = service.set_user_disabled(
        actor_user_id=" ADMIN-B", user_id=" USER-A ", disabled=True, expected_lifecycle_version=1
    )
    assert changed.transitioned and changed.revoked_sessions == 1
    assert service.list_sessions(
        limit=20,
        user_id=" USER-A ",
        after_created_at="2026-07-29T19:00:00Z",
        after_session_id=" SESSION-A ",
    ).items
    assert service.revoke_session(
        actor_user_id=" ADMIN-B ",
        current_session_id=" SESSION-B ",
        session_id=" SESSION-A ",
        expected_lifecycle_version=1,
        reason_code=" SECURITY_RESPONSE ",
    ).transitioned

    assert repository.calls == [
        (
            "list_users",
            {
                "as_of": NOW,
                "limit": 10,
                "after_username": "admin-a",
                "after_user_id": "user-a",
            },
        ),
        (
            "set_user_disabled",
            {
                "actor_user_id": "admin-b",
                "user_id": "user-a",
                "disabled": True,
                "expected_lifecycle_version": 1,
                "as_of": NOW,
            },
        ),
        (
            "list_sessions",
            {
                "as_of": NOW,
                "user_id": "user-a",
                "limit": 20,
                "after_created_at": "2026-07-29T19:00:00Z",
                "after_session_id": "session-a",
            },
        ),
        (
            "revoke_session",
            {
                "actor_user_id": "admin-b",
                "current_session_id": "session-b",
                "session_id": "session-a",
                "expected_lifecycle_version": 1,
                "reason_code": "security_response",
                "as_of": NOW,
            },
        ),
    ]


@pytest.mark.parametrize(
    ("operation", "code"),
    [
        (lambda service: service.list_users(limit=0), "identity_page_limit_invalid"),
        (lambda service: service.list_users(limit=201), "identity_page_limit_invalid"),
        (
            lambda service: service.list_users(limit=1, after_username="admin-a"),
            "identity_user_cursor_invalid",
        ),
        (
            lambda service: service.list_sessions(limit=1, after_session_id="session-a"),
            "identity_session_cursor_invalid",
        ),
        (
            lambda service: service.set_user_disabled(
                actor_user_id="user-a", user_id="user-a", disabled=True, expected_lifecycle_version=1
            ),
            "identity_self_disable_forbidden",
        ),
        (
            lambda service: service.set_user_disabled(
                actor_user_id="user-b", user_id="user-a", disabled=True, expected_lifecycle_version=0
            ),
            "identity_lifecycle_version_invalid",
        ),
        (
            lambda service: service.revoke_session(
                actor_user_id="user-b",
                current_session_id="session-b",
                session_id="session-a",
                expected_lifecycle_version=1,
                reason_code="free-form",
            ),
            "identity_revocation_reason_invalid",
        ),
    ],
)
def test_application_contract_rejects_unsafe_lifecycle_inputs(
    operation: Callable[[IdentityAdministrationApplicationService], object], code: str
) -> None:
    service = IdentityAdministrationApplicationService(_Repository(), clock=lambda: NOW)
    with pytest.raises(IdentityAdministrationError) as raised:
        operation(service)
    assert raised.value.code == code


@pytest.mark.parametrize(
    "clock",
    [
        lambda: datetime(2026, 7, 29, 20, 0),
        lambda: datetime(2026, 7, 29, 20, 0, 0, 1, tzinfo=UTC),
    ],
)
def test_application_contract_rejects_ambiguous_or_subsecond_time(clock: Callable[[], datetime]) -> None:
    service = IdentityAdministrationApplicationService(_Repository(), clock=clock)
    with pytest.raises(IdentityAdministrationError) as raised:
        service.list_users(limit=1)
    assert raised.value.code == "identity_time_invalid"


def test_identity_administration_operator_contract_is_in_source_manifest() -> None:
    manifest = {
        line.strip()
        for line in Path("MANIFEST.in").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    assert "include docs/operations/identity-administration.md" in manifest
    assert "include docs/adr/0195-authoritative-postgres-identity-lifecycle.md" in manifest
