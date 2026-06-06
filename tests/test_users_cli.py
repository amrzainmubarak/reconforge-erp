from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from reconforge.audit import list_audit_events
from reconforge.cli import app
from reconforge.db import connect, run_migrations

runner = CliRunner()


def _password_input(password: str = "Secret-123") -> str:
    return f"{password}\n{password}\n"


def test_users_cli_init_admin_list_and_roles(tmp_path: Path) -> None:
    db_path = tmp_path / "users.db"
    run_migrations(db_path)

    created = runner.invoke(
        app,
        ["users", "init-admin", "--db", str(db_path), "--username", "admin"],
        input=_password_input(),
    )
    listed = runner.invoke(app, ["users", "list", "--db", str(db_path)])
    roles = runner.invoke(app, ["roles", "list", "--db", str(db_path)])
    permissions = runner.invoke(app, ["roles", "permissions", "--db", str(db_path), "--role", "admin"])

    assert created.exit_code == 0
    assert "Local admin created" in created.output
    assert "Secret-123" not in created.output
    assert listed.exit_code == 0
    assert "admin" in listed.output
    assert "password" not in listed.output.lower()
    assert roles.exit_code == 0
    assert "auditor-readonly" in roles.output
    assert permissions.exit_code == 0
    assert "users.manage" in permissions.output
    assert "Traceback" not in created.output + listed.output + roles.output + permissions.output


def test_users_cli_add_check_permission_set_role_and_disable(tmp_path: Path) -> None:
    db_path = tmp_path / "reviewer.db"
    run_migrations(db_path)

    added = runner.invoke(
        app,
        ["users", "add", "--db", str(db_path), "--username", "reviewer", "--role", "reviewer"],
        input=_password_input(),
    )
    allowed = runner.invoke(
        app,
        ["users", "check-permission", "--db", str(db_path), "--username", "reviewer", "--permission", "audit.read"],
    )
    denied = runner.invoke(
        app,
        ["users", "check-permission", "--db", str(db_path), "--username", "reviewer", "--permission", "users.manage"],
    )
    changed = runner.invoke(
        app,
        ["users", "set-role", "--db", str(db_path), "--username", "reviewer", "--role", "auditor-readonly"],
    )
    disabled = runner.invoke(app, ["users", "disable", "--db", str(db_path), "--username", "reviewer"])

    assert added.exit_code == 0
    assert allowed.exit_code == 0
    assert "Permission allowed" in allowed.output
    assert denied.exit_code == 1
    assert "Permission denied" in denied.output
    assert changed.exit_code == 0
    assert disabled.exit_code == 0
    assert "Traceback" not in added.output + allowed.output + denied.output + changed.output + disabled.output

    connection = connect(db_path, require_exists=True)
    try:
        actions = [event.action for event in list_audit_events(connection)]
    finally:
        connection.close()
    assert "user_created" in actions
    assert "role_assigned" in actions
    assert "role_changed" in actions
    assert "user_disabled" in actions


def test_users_cli_duplicate_username_fails_without_traceback(tmp_path: Path) -> None:
    db_path = tmp_path / "duplicate.db"
    run_migrations(db_path)

    first = runner.invoke(
        app,
        ["users", "add", "--db", str(db_path), "--username", "reviewer", "--role", "reviewer"],
        input=_password_input(),
    )
    second = runner.invoke(
        app,
        ["users", "add", "--db", str(db_path), "--username", "reviewer", "--role", "reviewer"],
        input=_password_input("Different-123"),
    )

    assert first.exit_code == 0
    assert second.exit_code == 1
    assert "User already exists" in second.output
    assert "Traceback" not in second.output


def test_users_cli_missing_db_fails_without_traceback(tmp_path: Path) -> None:
    result = runner.invoke(app, ["users", "list", "--db", str(tmp_path / "missing.db")])

    assert result.exit_code == 1
    assert "Run 'reconforge db init' first" in result.output
    assert "Traceback" not in result.output
