from __future__ import annotations

from pathlib import Path

import pytest

from reconforge.audit import list_audit_events
from reconforge.auth import AuthServiceError, LocalAuthService, RoleRepository
from reconforge.db import connect, run_migrations


def test_default_roles_and_permissions_exist(tmp_path: Path) -> None:
    db_path = tmp_path / "rbac.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        repository = RoleRepository(connection)
        role_names = {role.name for role in repository.list_roles()}
        permission_names = {permission.name for permission in repository.list_permissions()}
    finally:
        connection.close()

    assert role_names == {"admin", "controller", "preparer", "reviewer", "auditor-readonly"}
    assert {
        "users.manage",
        "roles.manage",
        "db.read",
        "audit.read",
        "audit.verify",
        "reconciliation.prepare",
        "reconciliation.review",
        "reconciliation.approve",
        "controls.test",
        "evidence.read",
        "reports.read",
    } <= permission_names


def test_admin_user_creation_password_auth_and_no_plaintext_storage(tmp_path: Path) -> None:
    db_path = tmp_path / "auth.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = LocalAuthService(connection)
        user = service.init_admin(username="admin", password="Secret-123")
        stored = connection.execute(
            "SELECT password_hash, password_salt FROM users WHERE username = ?",
            ("admin",),
        ).fetchone()
        authenticated = service.authenticate_user(username="admin", password="Secret-123")
        wrong = service.authenticate_user(username="admin", password="wrong")
    finally:
        connection.close()

    assert user.username == "admin"
    assert authenticated is not None
    assert wrong is None
    assert stored is not None
    assert stored["password_hash"] != "Secret-123"
    assert stored["password_salt"] != "Secret-123"


def test_duplicate_username_fails_safely(tmp_path: Path) -> None:
    db_path = tmp_path / "duplicate.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = LocalAuthService(connection)
        service.create_user(username="reviewer", password="Secret-123", role="reviewer")
        with pytest.raises(AuthServiceError, match="User already exists"):
            service.create_user(username="reviewer", password="Other-123", role="reviewer")
    finally:
        connection.close()


def test_disabled_user_cannot_authenticate_or_have_permissions(tmp_path: Path) -> None:
    db_path = tmp_path / "disabled.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = LocalAuthService(connection)
        service.create_user(username="reviewer", password="Secret-123", role="reviewer")
        service.disable_user(username="reviewer")
        authenticated = service.authenticate_user(username="reviewer", password="Secret-123")
        allowed = service.user_has_permission(username="reviewer", permission="audit.read")
    finally:
        connection.close()

    assert authenticated is None
    assert not allowed


def test_role_assignment_and_permission_checks(tmp_path: Path) -> None:
    db_path = tmp_path / "permissions.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = LocalAuthService(connection)
        service.create_user(username="preparer", password="Secret-123", role="preparer")
        assert service.user_has_permission(username="preparer", permission="reconciliation.prepare")
        assert not service.user_has_permission(username="preparer", permission="audit.verify")

        service.set_single_role(username="preparer", role="auditor-readonly")
        roles = service.roles.user_roles("preparer")
        assert service.user_has_permission(username="preparer", permission="audit.verify")
    finally:
        connection.close()

    assert roles == ["auditor-readonly"]


def test_object_action_permission_check(tmp_path: Path) -> None:
    db_path = tmp_path / "object_permission.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = LocalAuthService(connection)
        service.create_user(username="reviewer", password="Secret-123", role="reviewer")
        can_review = service.user_can_perform_object_action(
            username="reviewer",
            object_type="reconciliation",
            action="review",
        )
        can_test_controls = service.user_can_perform_object_action(
            username="reviewer",
            object_type="controls",
            action="test",
        )
    finally:
        connection.close()

    assert can_review
    assert not can_test_controls


def test_sod_conflict_detection() -> None:
    service_actions = [("USR-1", "reconciliation", "REC-1", "prepare")]
    from reconforge.auth.rbac import check_sod_conflict

    conflict = check_sod_conflict(
        user_id="USR-1",
        object_type="reconciliation",
        object_id="REC-1",
        action="review",
        prior_actions=service_actions,
    )
    allowed = check_sod_conflict(
        user_id="USR-2",
        object_type="reconciliation",
        object_id="REC-1",
        action="review",
        prior_actions=service_actions,
    )

    assert not conflict.allowed
    assert "Separation of duties" in conflict.reason
    assert allowed.allowed


def test_audit_events_are_written_for_user_role_and_password_mutations(tmp_path: Path) -> None:
    db_path = tmp_path / "audit_mutations.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = LocalAuthService(connection)
        service.create_user(username="reviewer", password="Secret-123", role="reviewer")
        service.set_single_role(username="reviewer", role="auditor-readonly")
        service.change_password(username="reviewer", password="New-Secret-123")
        service.disable_user(username="reviewer")
        events = list_audit_events(connection)
    finally:
        connection.close()

    actions = [event.action for event in events]
    assert "user_created" in actions
    assert "role_assigned" in actions
    assert "role_changed" in actions
    assert "password_changed" in actions
    assert "user_disabled" in actions
    serialized_metadata = " ".join(str(event.metadata) for event in events)
    assert "Secret-123" not in serialized_metadata
    assert "New-Secret-123" not in serialized_metadata
