"""Command-line interface for ReconForge ERP."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Annotated, cast

import pandas as pd
import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from reconforge import __version__
from reconforge.ai.summaries import explain_exception_file
from reconforge.anonymizer.engine import anonymize_directory
from reconforge.api import create_api_app
from reconforge.audit import AuditLedgerError, list_audit_events, verify_audit_events
from reconforge.auth import AuthRepositoryError, AuthServiceError, LocalAuthService, RoleRepository
from reconforge.benchmark.runner import run_benchmark
from reconforge.close import (
    ALLOWED_CLOSE_STATUSES,
    close_summary_frame,
    close_tasks_frame,
    export_close_report,
    load_close_checklist,
    update_close_task_status,
    write_close_checklist,
)
from reconforge.config import load_config, write_default_config
from reconforge.control_matrix import export_control_matrix
from reconforge.dashboard.app import create_app
from reconforge.db import DatabaseError, connect, database_status, run_migrations
from reconforge.evidence.binder import generate_evidence_binder
from reconforge.generator.synthetic import generate_synthetic_dataset
from reconforge.io.excel import audit_metadata, write_excel_workbook
from reconforge.io.readers import read_required_datasets
from reconforge.io.writers import ensure_output_dir, frame_to_records, write_json, write_report_frames
from reconforge.mappings.inspector import inspect_mapping_inputs
from reconforge.mappings.profile_template import write_profile_template
from reconforge.mappings.validator import validate_mapping_pack
from reconforge.periods import compare_period_outputs
from reconforge.reconciliation.matching import MatchingStrategy
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.reconciliation.stock_gl import result_frames as stock_gl_result_frames
from reconforge.reconciliation.workorders import reconcile_workorders
from reconforge.reconciliation.workorders import result_frames as workorder_result_frames
from reconforge.reports.client_pack import generate_client_pack
from reconforge.reports.management_pack import generate_management_pack
from reconforge.reports.wip_aging import aging_summary, generate_wip_aging
from reconforge.review.state import (
    ALLOWED_STATUSES,
    collect_exception_frame,
    export_review_register,
    load_review_state,
    merge_review_state_with_exceptions,
    save_review_state,
    update_review_status,
)
from reconforge.rules.engine import run_rule_pack, write_rule_results
from reconforge.rules.explain import explain_rule
from reconforge.rules.loader import load_rule_pack
from reconforge.schemas import DatasetName
from reconforge.studio.app import create_studio_app
from reconforge.validators import issues_to_frame, validate_input_directory
from reconforge.variance import analyze_variance
from reconforge.workflow import WorkflowRepositoryError, WorkflowService, WorkflowServiceError

console = Console()
ALL_INTERFACES_HOST = ".".join(("0", "0", "0", "0"))
app = typer.Typer(help="ReconForge ERP reconciliation intelligence CLI.")
reconcile_app = typer.Typer(help="Run reconciliation controls.")
report_app = typer.Typer(help="Generate audit and management reports.")
rules_app = typer.Typer(help="Validate, list, and run control-pack rules.")
mappings_app = typer.Typer(help="Validate ERP mapping profiles.")
generate_app = typer.Typer(help="Generate synthetic ERP datasets.")
explain_app = typer.Typer(help="Explain exceptions and controls deterministically.")
review_app = typer.Typer(help="Review exceptions with local JSON state.")
demo_app = typer.Typer(help="Run first-time-user demo workflows.")
compare_app = typer.Typer(help="Compare generated exception outputs across periods.")
close_app = typer.Typer(help="Manage local close checklist workflow state.")
analyze_app = typer.Typer(help="Analyze local ReconForge output folders.")
controls_app = typer.Typer(help="Generate local control intelligence outputs.")
db_app = typer.Typer(help="Manage the local SQLite database foundation.")
audit_app = typer.Typer(help="Inspect local append-only audit events.")
users_app = typer.Typer(help="Manage local users for DB-backed workflows.")
roles_app = typer.Typer(help="Inspect local RBAC roles and permissions.")
workflow_app = typer.Typer(help="Manage local workflow state machine foundations.")
api_app = typer.Typer(help="Serve the local REST API foundation.")
app.add_typer(reconcile_app, name="reconcile")
app.add_typer(report_app, name="report")
app.add_typer(rules_app, name="rules")
app.add_typer(mappings_app, name="mappings")
app.add_typer(generate_app, name="generate")
app.add_typer(explain_app, name="explain")
app.add_typer(review_app, name="review")
app.add_typer(demo_app, name="demo")
app.add_typer(compare_app, name="compare")
app.add_typer(close_app, name="close")
app.add_typer(analyze_app, name="analyze")
app.add_typer(controls_app, name="controls")
app.add_typer(db_app, name="db")
app.add_typer(audit_app, name="audit")
app.add_typer(users_app, name="users")
app.add_typer(roles_app, name="roles")
app.add_typer(workflow_app, name="workflow")
app.add_typer(api_app, name="api")


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"ReconForge ERP {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[bool, typer.Option("--version", callback=_version_callback, help="Show version and exit.")] = False,
) -> None:
    """ReconForge ERP command group."""


def _print_frame(title: str, frame: pd.DataFrame, max_rows: int = 12) -> None:
    table = Table(title=title, show_lines=False)
    visible = frame.head(max_rows)
    for column in visible.columns:
        table.add_column(str(column))
    for _, row in visible.iterrows():
        table.add_row(*(str(row[column]) for column in visible.columns))
    console.print(table)
    if len(frame) > max_rows:
        console.print(f"[dim]Showing {max_rows} of {len(frame)} rows.[/dim]")


def _config_option(config_path: Path | None) -> Path | None:
    return config_path


def _print_success_paths(paths: list[Path]) -> None:
    for path in paths:
        console.print(f"[green]Written:[/green] {path}")


def _db_option(db_path: Path) -> Path:
    return db_path


def _prompt_password() -> str:
    return str(typer.prompt("Password", hide_input=True, confirmation_prompt=True))


def _auth_service(db_path: Path) -> tuple[LocalAuthService, sqlite3.Connection]:
    connection = connect(_db_option(db_path), require_exists=True)
    try:
        service = LocalAuthService(connection)
    except (DatabaseError, AuthRepositoryError, AuthServiceError):
        connection.close()
        raise
    return service, connection


def _workflow_service(db_path: Path) -> tuple[WorkflowService, sqlite3.Connection]:
    connection = connect(_db_option(db_path), require_exists=True)
    try:
        service = WorkflowService(connection)
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError):
        connection.close()
        raise
    return service, connection


@api_app.command("serve")
def api_serve_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    host: Annotated[str, typer.Option("--host", help="Bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Bind port.")] = 8765,
) -> None:
    """Start the local REST API server."""

    try:
        status = database_status(_db_option(db_path))
        if status.pending_versions:
            console.print("[red]ReconForge database has pending migrations. Run 'reconforge db migrate' first.[/red]")
            raise typer.Exit(code=1)
    except DatabaseError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if host == ALL_INTERFACES_HOST:
        console.print(f"[yellow]Warning:[/yellow] binding to {ALL_INTERFACES_HOST} exposes the local API beyond localhost. This is not a public internet deployment mode.")
    console.print(f"[green]Starting ReconForge local API:[/green] http://{host}:{port}")
    uvicorn.run(create_api_app(db_path), host=host, port=port, log_level="info")


@db_app.command("init")
def db_init_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Initialize the local SQLite database."""

    try:
        status = run_migrations(_db_option(db_path))
    except DatabaseError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    applied = ", ".join(str(version) for version in status.applied_versions) or "already current"
    console.print(f"[green]Database ready:[/green] {status.path}")
    console.print(f"Schema version: {status.current_version}/{status.latest_version} | Applied: {applied}")


@db_app.command("migrate")
def db_migrate_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Apply pending local SQLite migrations."""

    try:
        status = run_migrations(_db_option(db_path))
    except DatabaseError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    applied = ", ".join(str(version) for version in status.applied_versions) or "none"
    console.print(f"[green]Database migrated:[/green] {status.path}")
    console.print(f"Schema version: {status.current_version}/{status.latest_version} | Applied now: {applied}")


@db_app.command("status")
def db_status_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Show local SQLite migration status."""

    try:
        status = database_status(_db_option(db_path))
    except DatabaseError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    table = Table(title="ReconForge Database")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Path", str(status.path))
    table.add_row("Current version", str(status.current_version))
    table.add_row("Latest version", str(status.latest_version))
    table.add_row("Applied versions", ", ".join(str(version) for version in status.applied_versions) or "none")
    table.add_row("Pending versions", ", ".join(str(version) for version in status.pending_versions) or "none")
    console.print(table)


@audit_app.command("list")
def audit_list_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    limit: Annotated[int | None, typer.Option("--limit", help="Maximum number of audit events to show.")] = None,
) -> None:
    """List local audit events."""

    try:
        connection = connect(_db_option(db_path), require_exists=True)
        try:
            events = list_audit_events(connection, limit=limit)
        finally:
            connection.close()
    except (DatabaseError, AuditLedgerError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    if not events:
        console.print("[yellow]No audit events found.[/yellow]")
        return
    table = Table(title="Audit Events")
    table.add_column("Seq", justify="right")
    table.add_column("Actor")
    table.add_column("Object")
    table.add_column("Action")
    table.add_column("Created")
    table.add_column("Hash")
    for event in events:
        table.add_row(
            str(event.sequence),
            event.actor_label,
            f"{event.object_type}:{event.object_id}",
            event.action,
            event.created_at,
            event.event_hash[:12],
        )
    console.print(table)


@audit_app.command("verify")
def audit_verify_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Verify the local audit event hash chain."""

    try:
        connection = connect(_db_option(db_path), require_exists=True)
        try:
            result = verify_audit_events(connection)
        finally:
            connection.close()
    except (DatabaseError, AuditLedgerError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    if result.ok:
        console.print(f"[green]Audit ledger verified:[/green] {result.checked_events} events | head {result.head_hash[:12]}")
        return

    table = Table(title="Audit Verification Issues")
    table.add_column("Sequence")
    table.add_column("Issue")
    for issue in result.issues:
        table.add_row("" if issue.sequence is None else str(issue.sequence), issue.message)
    console.print(table)
    console.print("[red]Audit ledger verification failed.[/red]")
    raise typer.Exit(code=1)


@users_app.command("init-admin")
def users_init_admin_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    username: Annotated[str, typer.Option("--username", help="Admin username.")] = "admin",
) -> None:
    """Create the first local admin user."""

    password = _prompt_password()
    try:
        service, connection = _auth_service(db_path)
        try:
            user = service.init_admin(username=username, password=password)
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Local admin created:[/green] {user.username}")


@users_app.command("add")
def users_add_command(
    username: Annotated[str, typer.Option("--username", help="Username to create.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    role: Annotated[str, typer.Option("--role", help="Built-in role to assign.")] = "reviewer",
    display_name: Annotated[str | None, typer.Option("--display-name", help="Optional display name.")] = None,
    email: Annotated[str | None, typer.Option("--email", help="Optional email reference.")] = None,
) -> None:
    """Create a local user and assign one role."""

    password = _prompt_password()
    try:
        service, connection = _auth_service(db_path)
        try:
            user = service.create_user(
                username=username,
                password=password,
                role=role,
                display_name=display_name,
                email=email,
            )
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Local user created:[/green] {user.username} | role: {role}")


@users_app.command("list")
def users_list_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List local users without credential data."""

    try:
        service, connection = _auth_service(db_path)
        try:
            users = service.users.list()
            roles_by_user = {user.username: service.roles.user_roles(user.username) for user in users}
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if not users:
        console.print("[yellow]No local users found.[/yellow]")
        return
    table = Table(title="Local Users")
    table.add_column("Username")
    table.add_column("Display Name")
    table.add_column("Disabled")
    table.add_column("Roles")
    table.add_column("Created")
    for user in users:
        table.add_row(
            user.username,
            user.display_name,
            "yes" if user.disabled else "no",
            ", ".join(roles_by_user[user.username]) or "none",
            user.created_at,
        )
    console.print(table)


@users_app.command("disable")
def users_disable_command(
    username: Annotated[str, typer.Option("--username", help="Username to disable.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Disable a local user."""

    try:
        service, connection = _auth_service(db_path)
        try:
            user = service.disable_user(username=username)
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Local user disabled:[/green] {user.username}")


@users_app.command("set-role")
def users_set_role_command(
    username: Annotated[str, typer.Option("--username", help="Username to update.")],
    role: Annotated[str, typer.Option("--role", help="Role to set.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Replace a local user's roles with one role."""

    try:
        service, connection = _auth_service(db_path)
        try:
            service.set_single_role(username=username, role=role)
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Local user role updated:[/green] {username} | role: {role}")


@users_app.command("check-permission")
def users_check_permission_command(
    username: Annotated[str, typer.Option("--username", help="Username to check.")],
    permission: Annotated[str, typer.Option("--permission", help="Permission name to check.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Check whether a local user has a permission."""

    try:
        service, connection = _auth_service(db_path)
        try:
            allowed = service.user_has_permission(username=username, permission=permission)
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if allowed:
        console.print(f"[green]Permission allowed:[/green] {username} | {permission}")
        return
    console.print(f"[red]Permission denied:[/red] {username} | {permission}")
    raise typer.Exit(code=1)


@roles_app.command("list")
def roles_list_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List local built-in roles."""

    try:
        connection = connect(_db_option(db_path), require_exists=True)
        try:
            repository = RoleRepository(connection)
            roles = repository.list_roles()
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    table = Table(title="Local Roles")
    table.add_column("Role")
    for role in roles:
        table.add_row(role.name)
    console.print(table)


@roles_app.command("permissions")
def roles_permissions_command(
    role: Annotated[str, typer.Option("--role", help="Role to inspect.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List permissions assigned to one local role."""

    try:
        connection = connect(_db_option(db_path), require_exists=True)
        try:
            repository = RoleRepository(connection)
            permissions = repository.role_permissions(role)
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    table = Table(title=f"Role Permissions: {role}")
    table.add_column("Permission")
    for permission in permissions:
        table.add_row(permission)
    console.print(table)


@workflow_app.command("transitions")
def workflow_transitions_command(
    object_type: Annotated[str, typer.Option("--object-type", help="Workflow object type.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List allowed transition templates for a workflow object type."""

    try:
        service, connection = _workflow_service(db_path)
        try:
            transitions = service.list_allowed_transitions(object_type=object_type)
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if not transitions:
        console.print("[yellow]No workflow transitions found.[/yellow]")
        return
    table = Table(title=f"Workflow Transitions: {object_type}")
    table.add_column("From")
    table.add_column("To")
    table.add_column("Permission")
    table.add_column("SoD")
    table.add_column("Reason")
    for transition in transitions:
        table.add_row(
            transition.from_status,
            transition.to_status,
            transition.required_permission or "",
            transition.sod_rule or "",
            "required" if transition.reason_required else "",
        )
    console.print(table)


@workflow_app.command("init-object")
def workflow_init_object_command(
    object_type: Annotated[str, typer.Option("--object-type", help="Workflow object type.")],
    object_id: Annotated[str, typer.Option("--object-id", help="Workflow object identifier.")],
    status: Annotated[str, typer.Option("--status", help="Initial workflow status.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Initialize a local workflow object."""

    try:
        service, connection = _workflow_service(db_path)
        try:
            workflow_object = service.initialize_object(object_type=object_type, object_id=object_id, status=status)
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Workflow object initialized:[/green] {workflow_object.object_type}:{workflow_object.object_id} | {workflow_object.status}")


@workflow_app.command("status")
def workflow_status_command(
    object_type: Annotated[str, typer.Option("--object-type", help="Workflow object type.")],
    object_id: Annotated[str, typer.Option("--object-id", help="Workflow object identifier.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Show local workflow object status."""

    try:
        service, connection = _workflow_service(db_path)
        try:
            workflow_object = service.get_status(object_type=object_type, object_id=object_id)
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    table = Table(title="Workflow Status")
    table.add_column("Object")
    table.add_column("Status")
    table.add_column("Updated")
    table.add_row(f"{workflow_object.object_type}:{workflow_object.object_id}", workflow_object.status, workflow_object.updated_at)
    console.print(table)


@workflow_app.command("transition")
def workflow_transition_command(
    object_type: Annotated[str, typer.Option("--object-type", help="Workflow object type.")],
    object_id: Annotated[str, typer.Option("--object-id", help="Workflow object identifier.")],
    to_status: Annotated[str, typer.Option("--to-status", help="Target workflow status.")],
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
    reason: Annotated[str, typer.Option("--reason", help="Transition reason when required.")] = "",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Perform a local workflow transition."""

    try:
        service, connection = _workflow_service(db_path)
        try:
            workflow_object = service.perform_transition(
                object_type=object_type,
                object_id=object_id,
                to_status=to_status,
                actor_label=actor,
                reason=reason,
            )
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Workflow transitioned:[/green] {workflow_object.object_type}:{workflow_object.object_id} | {workflow_object.status}")


@workflow_app.command("history")
def workflow_history_command(
    object_type: Annotated[str, typer.Option("--object-type", help="Workflow object type.")],
    object_id: Annotated[str, typer.Option("--object-id", help="Workflow object identifier.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List local workflow transition history."""

    try:
        service, connection = _workflow_service(db_path)
        try:
            events = service.list_history(object_type=object_type, object_id=object_id)
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if not events:
        console.print("[yellow]No workflow transition history found.[/yellow]")
        return
    table = Table(title=f"Workflow History: {object_type}:{object_id}")
    table.add_column("From")
    table.add_column("To")
    table.add_column("Actor")
    table.add_column("Reason")
    table.add_column("Created")
    for event in events:
        table.add_row(event.from_status, event.to_status, event.actor_label, event.reason, event.created_at)
    console.print(table)


@app.command("init")
def init_workspace(
    workspace: Annotated[Path, typer.Argument(help="Workspace directory to create.")] = Path("."),
) -> None:
    """Create a ReconForge project workspace."""

    for folder in ("input", "output", "config", "reports", "logs"):
        (workspace / folder).mkdir(parents=True, exist_ok=True)
    config_path = write_default_config(workspace / "config" / "reconforge.yml")
    readme_path = workspace / "README.md"
    if not readme_path.exists():
        readme_path.write_text(
            "# ReconForge Workspace\n\nPlace ERP exports in `input/` and generated reports will be written to `output/` or `reports/`.\n",
            encoding="utf-8",
        )
    console.print(f"[green]Workspace ready:[/green] {workspace}")
    console.print(f"Default config: {config_path}")


@app.command("validate")
def validate(
    input_path: Annotated[Path, typer.Argument(help="Directory containing ERP input files.")],
) -> None:
    """Validate input files and cross-references."""

    issues = validate_input_directory(input_path)
    frame = issues_to_frame(issues)
    if frame.empty:
        console.print("[green]Validation passed with no issues.[/green]")
        return
    _print_frame("Validation Issues", frame)
    error_count = int(frame["severity"].astype(str).eq("error").sum())
    warning_count = int(frame["severity"].astype(str).eq("warning").sum())
    console.print(f"Errors: {error_count} | Warnings: {warning_count}")
    if error_count:
        raise typer.Exit(code=1)


@reconcile_app.command("stock-gl")
def reconcile_stock_gl_command(
    input_path: Annotated[Path, typer.Option("--input", help="Directory containing stock_moves and gl_entries.")],
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path("config/reconforge.yml"),
    output_path: Annotated[Path, typer.Option("--output", help="Output directory.")] = Path("output"),
    matching_strategy: Annotated[
        str,
        typer.Option("--matching-strategy", help="Matching strategy: standard, strict, aggressive, audit-safe."),
    ] = "standard",
) -> None:
    """Compare stock movements with GL postings."""

    config = load_config(_config_option(config_path))
    datasets = read_required_datasets(input_path, [DatasetName.STOCK_MOVES, DatasetName.GL_ENTRIES])
    if matching_strategy not in {"standard", "strict", "aggressive", "audit-safe"}:
        console.print("[red]matching strategy must be one of: standard, strict, aggressive, audit-safe[/red]")
        raise typer.Exit(code=1)
    result = reconcile_stock_gl(
        datasets[DatasetName.STOCK_MOVES],
        datasets[DatasetName.GL_ENTRIES],
        config,
        matching_strategy=cast(MatchingStrategy, matching_strategy),
    )
    output_dir = ensure_output_dir(output_path)
    frames = stock_gl_result_frames(result)
    write_report_frames(frames, output_dir, "stock_gl")
    workbook_path = write_excel_workbook(
        frames,
        output_dir / "stock_gl_reconciliation.xlsx",
        metadata=audit_metadata(config.company_name, "Stock to GL Reconciliation", config.output_currency),
    )
    write_json(
        {
            "summary": frame_to_records(result.summary),
            "matched_transactions": frame_to_records(result.matched_transactions),
            "all_exceptions": frame_to_records(result.all_exceptions),
        },
        output_dir,
        "stock_gl_reconciliation",
    )
    _print_frame("Stock-GL Summary", result.summary)
    console.print(f"[green]Stock-GL reconciliation written to:[/green] {workbook_path}")


@reconcile_app.command("workorders")
def reconcile_workorders_command(
    input_path: Annotated[Path, typer.Option("--input", help="Directory containing workshop ERP files.")],
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path("config/reconforge.yml"),
    output_path: Annotated[Path, typer.Option("--output", help="Output directory.")] = Path("output"),
) -> None:
    """Reconcile spare-parts issues, work orders, purchase orders, returns, and invoices."""

    config = load_config(_config_option(config_path))
    datasets = read_required_datasets(
        input_path,
        [
            DatasetName.STOCK_MOVES,
            DatasetName.WORK_ORDERS,
            DatasetName.PURCHASE_ORDERS,
            DatasetName.OLD_PARTS_RETURNS,
            DatasetName.INVOICES,
        ],
    )
    result = reconcile_workorders(
        datasets[DatasetName.STOCK_MOVES],
        datasets[DatasetName.WORK_ORDERS],
        datasets[DatasetName.PURCHASE_ORDERS],
        datasets[DatasetName.OLD_PARTS_RETURNS],
        datasets[DatasetName.INVOICES],
        config,
    )
    output_dir = ensure_output_dir(output_path)
    frames = workorder_result_frames(result)
    write_report_frames(frames, output_dir, "workorders")
    workbook_path = write_excel_workbook(
        frames,
        output_dir / "workorder_reconciliation.xlsx",
        metadata=audit_metadata(config.company_name, "Work Order Reconciliation", config.output_currency),
    )
    write_json(
        {"summary": frame_to_records(result.summary), "all_exceptions": frame_to_records(result.all_exceptions)},
        output_dir,
        "workorder_reconciliation",
    )
    _print_frame("Work-Order Summary", result.summary)
    console.print(f"[green]Work-order reconciliation written to:[/green] {workbook_path}")


@report_app.command("wip-aging")
def wip_aging_command(
    input_path: Annotated[Path, typer.Option("--input", help="Directory containing work_orders.")],
    output_path: Annotated[Path, typer.Option("--output", help="Output directory.")] = Path("output"),
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path("config/reconforge.yml"),
) -> None:
    """Generate WIP aging by work order, customer, equipment, department, and bucket."""

    config = load_config(_config_option(config_path))
    datasets = read_required_datasets(input_path, [DatasetName.WORK_ORDERS])
    wip = generate_wip_aging(datasets[DatasetName.WORK_ORDERS], config)
    summary = aging_summary(wip)
    output_dir = ensure_output_dir(output_path)
    frames = {"wip_aging": wip, "wip_aging_summary": summary}
    write_report_frames(frames, output_dir, "wip")
    workbook_path = write_excel_workbook(
        frames,
        output_dir / "wip_aging.xlsx",
        metadata=audit_metadata(config.company_name, "WIP Aging", config.output_currency),
    )
    write_json({"wip_aging": frame_to_records(wip), "summary": frame_to_records(summary)}, output_dir, "wip_aging")
    _print_frame("WIP Aging Summary", summary)
    console.print(f"[green]WIP aging report written to:[/green] {workbook_path}")


@report_app.command("management-pack")
def management_pack_command(
    input_path: Annotated[Path, typer.Option("--input", help="Directory containing all sample ERP files.")],
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path("config/reconforge.yml"),
    output_path: Annotated[Path, typer.Option("--output", help="Output directory.")] = Path("output"),
) -> None:
    """Generate a complete Excel management pack and companion outputs."""

    config = load_config(_config_option(config_path))
    datasets = read_required_datasets(
        input_path,
        [
            DatasetName.STOCK_MOVES,
            DatasetName.GL_ENTRIES,
            DatasetName.WORK_ORDERS,
            DatasetName.PURCHASE_ORDERS,
            DatasetName.OLD_PARTS_RETURNS,
            DatasetName.INVOICES,
        ],
    )
    stock_result = reconcile_stock_gl(datasets[DatasetName.STOCK_MOVES], datasets[DatasetName.GL_ENTRIES], config)
    workorder_result = reconcile_workorders(
        datasets[DatasetName.STOCK_MOVES],
        datasets[DatasetName.WORK_ORDERS],
        datasets[DatasetName.PURCHASE_ORDERS],
        datasets[DatasetName.OLD_PARTS_RETURNS],
        datasets[DatasetName.INVOICES],
        config,
    )
    wip = generate_wip_aging(datasets[DatasetName.WORK_ORDERS], config)
    artifacts = generate_management_pack(input_path, ensure_output_dir(output_path), config, stock_result, workorder_result, wip)
    console.print(f"[green]Management pack:[/green] {artifacts.excel_path}")
    console.print(f"[green]JSON summary:[/green] {artifacts.json_path}")
    console.print(f"[green]HTML dashboard report:[/green] {artifacts.html_path}")


@report_app.command("evidence-binder")
def evidence_binder_command(
    input_path: Annotated[Path, typer.Option("--input", help="Generated ReconForge output directory.")],
    output_path: Annotated[Path, typer.Option("--output", help="Evidence binder output directory.")] = Path("output/evidence"),
) -> None:
    """Generate audit evidence folders for High and Critical exceptions."""

    artifacts = generate_evidence_binder(input_path, output_path)
    console.print(f"[green]Evidence cases generated:[/green] {len(artifacts)}")
    if artifacts:
        _print_frame("Evidence Cases", pd.DataFrame([artifact.model_dump() for artifact in artifacts]))


@report_app.command("client-pack")
def client_pack_command(
    input_path: Annotated[Path, typer.Option("--input", help="Generated ReconForge output directory.")] = Path("output"),
    output_path: Annotated[Path, typer.Option("--output", help="Client handoff pack directory.")] = Path("output/client_pack"),
    redact_names: Annotated[bool, typer.Option("--redact-names", help="Redact customer, supplier, employee, reviewer, and equipment identifiers where practical.")] = False,
    redact_amounts: Annotated[bool, typer.Option("--redact-amounts", help="Bucket or redact monetary values where practical.")] = False,
    exclude_raw_records: Annotated[bool, typer.Option("--exclude-raw-records", help="Exclude source-record evidence extracts from the pack.")] = False,
    summary_only: Annotated[bool, typer.Option("--summary-only", help="Create only generated handoff notes plus the source summary when available.")] = False,
    exclude_evidence: Annotated[bool, typer.Option("--exclude-evidence", help="Exclude the evidence folder from the client pack.")] = False,
    include_manifest_checksums: Annotated[bool, typer.Option("--include-manifest-checksums", help="Add SHA-256 checksums for included client-pack files.")] = False,
) -> None:
    """Create a local consultant/client handoff folder from generated outputs."""

    try:
        artifacts = generate_client_pack(
            input_path,
            output_path,
            redact_names=redact_names,
            redact_amounts=redact_amounts,
            exclude_raw_records=exclude_raw_records,
            summary_only=summary_only,
            exclude_evidence=exclude_evidence,
            include_manifest_checksums=include_manifest_checksums,
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Client handoff pack:[/green] {artifacts.output_dir}")
    console.print(
        f"Included files: {len(artifacts.included_files)} | Missing optional files: {len(artifacts.missing_optional_files)} | Excluded files: {len(artifacts.excluded_files)}",
    )
    _print_success_paths(artifacts.included_files)


@rules_app.command("validate")
def rules_validate_command(
    pack_path: Annotated[Path, typer.Option("--pack", help="Control pack directory.")],
) -> None:
    """Validate a control pack."""

    pack = load_rule_pack(pack_path)
    console.print(f"[green]Control pack valid:[/green] {pack.metadata.pack_id} ({len(pack.rules)} rules)")


@mappings_app.command("validate")
def mappings_validate_command(
    pack_path: Annotated[Path, typer.Option("--pack", help="ERP mapping control-pack directory.")],
) -> None:
    """Validate an ERP mapping profile and its control-pack files."""

    result = validate_mapping_pack(pack_path)
    table = Table(title=f"Mapping Profile Validation: {result.pack_path}")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for check in result.checks:
        style = "green" if check.passed else "red"
        table.add_row(check.name, f"[{style}]{check.status}[/{style}]", check.detail)
    console.print(table)
    passed = sum(1 for check in result.checks if check.passed)
    failed = len(result.checks) - passed
    summary_style = "green" if result.passed else "red"
    console.print(f"[{summary_style}]Summary: {passed} passed, {failed} failed[/{summary_style}]")
    if not result.passed:
        raise typer.Exit(code=1)


def _run_mapping_inspection(input_path: Path, pack_path: Path, output_path: Path) -> None:
    try:
        result = inspect_mapping_inputs(input_path, pack_path, output_path)
    except (OSError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    summary = result.summary
    table = Table(title=f"Mapping Inspection: {result.profile_id}")
    table.add_column("Metric")
    table.add_column("Value")
    for key, value in summary.items():
        table.add_row(key.replace("_", " "), str(value))
    console.print(table)
    _print_success_paths([result.report_markdown_path, result.report_json_path])


@mappings_app.command("inspect")
def mappings_inspect_command(
    input_path: Annotated[Path, typer.Option("--input", help="Folder containing local CSV/XLSX ERP exports.")],
    pack_path: Annotated[Path, typer.Option("--pack", help="ERP mapping control-pack directory.")],
    output_path: Annotated[Path, typer.Option("--output", help="Mapping inspection report directory.")] = Path("output/mapping_wizard"),
) -> None:
    """Inspect local export headers against an ERP mapping profile."""

    _run_mapping_inspection(input_path, pack_path, output_path)


@mappings_app.command("wizard")
def mappings_wizard_command(
    input_path: Annotated[Path, typer.Option("--input", help="Folder containing local CSV/XLSX ERP exports.")],
    pack_path: Annotated[Path, typer.Option("--pack", help="ERP mapping control-pack directory.")],
    output_path: Annotated[Path, typer.Option("--output", help="Mapping inspection report directory.")] = Path("output/mapping_wizard"),
) -> None:
    """Generate a draft local mapping report for ERP exports."""

    _run_mapping_inspection(input_path, pack_path, output_path)


@mappings_app.command("profile-template")
def mappings_profile_template_command(
    output_path: Annotated[Path, typer.Option("--output", help="Profile template output directory.")] = Path("output/profile_template"),
) -> None:
    """Generate a local generic CSV mapping profile template."""

    artifacts = write_profile_template(output_path)
    _print_success_paths([artifacts.mapping_template_path, artifacts.guide_path])


@rules_app.command("list")
def rules_list_command(
    pack_path: Annotated[Path, typer.Option("--pack", help="Control pack directory.")],
) -> None:
    """List rules in a control pack."""

    pack = load_rule_pack(pack_path)
    frame = pd.DataFrame(
        [
            {
                "rule_id": rule.rule_id,
                "rule_name": rule.rule_name,
                "severity": rule.severity,
                "entity_type": rule.entity_type,
                "source_file": rule.source_file,
                "risk_impact": rule.risk_impact,
            }
            for rule in pack.rules
        ],
    )
    _print_frame(f"Rules: {pack.metadata.name}", frame, max_rows=100)


@rules_app.command("run")
def rules_run_command(
    input_path: Annotated[Path, typer.Option("--input", help="Directory containing ERP input files.")],
    pack_path: Annotated[Path, typer.Option("--pack", help="Control pack directory.")],
    output_path: Annotated[Path, typer.Option("--output", help="Rule output directory.")] = Path("output/rules"),
) -> None:
    """Run a control pack against ERP exports."""

    results = run_rule_pack(input_path, pack_path)
    paths = write_rule_results(results, output_path)
    console.print(f"[green]Rule results:[/green] {len(results)} triggered controls")
    _print_success_paths(paths)


@rules_app.command("explain")
def rules_explain_command(
    pack_path: Annotated[Path, typer.Option("--pack", help="Control pack directory.")],
    rule_id: Annotated[str, typer.Option("--rule", help="Rule ID to explain.")],
) -> None:
    """Explain a control-pack rule in deterministic plain English."""

    try:
        console.print(explain_rule(str(pack_path), rule_id))
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


@app.command("anonymize")
def anonymize_command(
    input_path: Annotated[Path, typer.Option("--input", help="Input ERP export directory.")],
    output_path: Annotated[Path, typer.Option("--output", help="Anonymized output directory.")],
    mask_amounts: Annotated[bool, typer.Option("--mask-amounts", help="Mask monetary amounts.")] = False,
    amount_noise_percent: Annotated[float, typer.Option("--amount-noise-percent", help="Maximum percentage noise for masked amounts.")] = 15.0,
    seed: Annotated[int, typer.Option("--seed", help="Deterministic anonymization seed.")] = 42,
    preserve_dates: Annotated[bool, typer.Option("--preserve-dates", help="Keep dates unchanged.")] = False,
    date_shift_days: Annotated[int, typer.Option("--date-shift-days", help="Shift dates by this many days.")] = 0,
    profile: Annotated[str, typer.Option("--profile", help="Anonymization profile: consulting-safe or public-demo.")] = "consulting-safe",
) -> None:
    """Anonymize ERP exports while preserving referential integrity."""

    paths = anonymize_directory(
        input_path,
        output_path,
        mask_amounts=mask_amounts,
        amount_noise_percent=amount_noise_percent,
        seed=seed,
        preserve_dates=preserve_dates,
        date_shift_days=date_shift_days,
        profile=profile,
    )
    console.print(f"[green]Anonymized files:[/green] {len(paths)}")
    _print_success_paths(paths)


@generate_app.command("synthetic")
def generate_synthetic_command(
    rows: Annotated[int, typer.Option("--rows", help="Number of stock movement rows to generate.", min=1)] = 1000,
    output_path: Annotated[Path, typer.Option("--output", help="Synthetic output directory.")] = Path("benchmarks/small_1k"),
    exception_rate: Annotated[float, typer.Option("--exception-rate", help="Approximate exception rate.")] = 0.15,
    critical_rate: Annotated[float, typer.Option("--critical-rate", help="Approximate critical exception rate.")] = 0.05,
    seed: Annotated[int, typer.Option("--seed", help="Deterministic generation seed.")] = 42,
    industry: Annotated[str, typer.Option("--industry", help="Industry profile: workshop, manufacturing, fleet, dealership, service.")] = "workshop",
    currency: Annotated[str, typer.Option("--currency", help="Output currency code for synthetic monetary rows.")] = "USD",
) -> None:
    """Generate synthetic ERP CSV exports matching ReconForge schema."""

    paths = generate_synthetic_dataset(
        rows,
        output_path,
        exception_rate=exception_rate,
        critical_rate=critical_rate,
        seed=seed,
        industry=industry,
        currency=currency,
    )
    console.print(f"[green]Synthetic dataset generated:[/green] {output_path}")
    _print_success_paths(paths)


@app.command("benchmark")
def benchmark_command(
    input_path: Annotated[Path, typer.Option("--input", help="Input dataset directory.")],
    engine: Annotated[str, typer.Option("--engine", help="Benchmark engine: pandas or duckdb.")] = "pandas",
    output_path: Annotated[Path, typer.Option("--output", help="Benchmark output directory.")] = Path("output/benchmark"),
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path("config/reconforge.yml"),
) -> None:
    """Benchmark reconciliation runtime and output metrics."""

    try:
        metrics = run_benchmark(input_path, output_path, engine_name=engine, config_path=config_path)
    except (ValueError, RuntimeError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    _print_frame("Benchmark", pd.DataFrame([metrics.to_dict()]))


@explain_app.command("exception")
def explain_exception_command(
    input_path: Annotated[Path, typer.Option("--input", help="Local JSON exception file.")],
    exception_id: Annotated[str, typer.Option("--exception-id", help="Exception ID, rule ID, move ID, or entry ID.")],
) -> None:
    """Explain an exception without requiring an AI API."""

    try:
        console.print(explain_exception_file(input_path, exception_id))
    except (OSError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


@review_app.command("list")
def review_list_command(
    input_path: Annotated[Path, typer.Option("--input", help="Generated ReconForge output directory.")] = Path("output"),
) -> None:
    """List local exceptions with review status."""

    state_path = input_path / "review_state.json"
    exceptions = collect_exception_frame(input_path)
    merged = merge_review_state_with_exceptions(exceptions, load_review_state(state_path))
    if merged.empty:
        console.print("[yellow]No generated exceptions found.[/yellow]")
        return
    columns = [
        "exception_id",
        "status",
        "reviewer",
        "updated_at",
        "severity",
        "exception_type",
        "amount_impact",
        "source_file",
    ]
    visible = merged[[column for column in columns if column in merged.columns]]
    _print_frame("Exception Review State", visible, max_rows=100)
    if "status" in merged.columns:
        counts = merged["status"].astype(str).value_counts().to_dict()
        summary = " | ".join(f"{status}: {count}" for status, count in counts.items())
        console.print(f"[dim]Review statuses:[/dim] {summary}")


@review_app.command("set-status")
def review_set_status_command(
    exception_id: Annotated[str, typer.Option("--exception-id", help="Exception ID to update.")],
    status: Annotated[str, typer.Option("--status", help=f"Status: {', '.join(ALLOWED_STATUSES)}")],
    input_path: Annotated[Path, typer.Option("--input", help="Generated ReconForge output directory.")] = Path("output"),
    reviewer: Annotated[str, typer.Option("--reviewer", help="Reviewer name or initials.")] = "",
    note: Annotated[str, typer.Option("--note", help="Reviewer note.")] = "",
    decision_reason: Annotated[str, typer.Option("--decision-reason", help="Decision reason.")] = "",
    accepted_risk_reason: Annotated[str, typer.Option("--accepted-risk-reason", help="Accepted-risk reason.")] = "",
    escalation_owner: Annotated[str, typer.Option("--escalation-owner", help="Escalation owner.")] = "",
    prepared_by: Annotated[str, typer.Option("--prepared-by", help="Preparer name or role for workflow metadata.")] = "",
    prepared_at: Annotated[str, typer.Option("--prepared-at", help="Optional prepared timestamp or date.")] = "",
    reviewed_by: Annotated[str, typer.Option("--reviewed-by", help="Reviewer name or role for workflow metadata.")] = "",
    reviewed_at: Annotated[str, typer.Option("--reviewed-at", help="Optional reviewed timestamp or date.")] = "",
    certification_status: Annotated[str, typer.Option("--certification-status", help="Workflow certification status metadata.")] = "",
    certification_note: Annotated[str, typer.Option("--certification-note", help="Workflow certification note.")] = "",
) -> None:
    """Set local review status for one exception."""

    state_path = input_path / "review_state.json"
    state = load_review_state(state_path)
    try:
        entry = update_review_status(
            exception_id,
            status,
            state,
            reviewer=reviewer,
            note=note,
            decision_reason=decision_reason,
            accepted_risk_reason=accepted_risk_reason,
            escalation_owner=escalation_owner,
            prepared_by=prepared_by,
            prepared_at=prepared_at,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
            certification_status=certification_status,
            certification_note=certification_note,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    save_review_state(state_path, state)
    console.print(
        f"[green]Review updated:[/green] {entry['exception_id']} | {entry['status']} | {state_path}",
    )


@review_app.command("export")
def review_export_command(
    input_path: Annotated[Path, typer.Option("--input", help="Generated ReconForge output directory.")] = Path("output"),
    output_path: Annotated[Path, typer.Option("--output", help="Review register workbook path.")] = Path("output/review_register.xlsx"),
) -> None:
    """Export exception review state as an Excel register."""

    path = export_review_register(input_path, output_path)
    console.print(f"[green]Review register written:[/green] {path}")


@close_app.command("init")
def close_init_command(
    output_path: Annotated[Path, typer.Option("--output", help="Close checklist output directory.")] = Path("output/close"),
    template_path: Annotated[Path | None, typer.Option("--template", help="Optional local JSON/YAML checklist template.")] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing close checklist.")] = False,
) -> None:
    """Create a local close checklist JSON file."""

    try:
        path = write_close_checklist(output_path, template_path=template_path, force=force)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Close checklist:[/green] {path}")


@close_app.command("list")
def close_list_command(
    input_path: Annotated[Path, typer.Option("--input", help="Close checklist directory or JSON file.")] = Path("output/close"),
) -> None:
    """List local close checklist tasks."""

    try:
        checklist = load_close_checklist(input_path)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    tasks = close_tasks_frame(checklist)
    if tasks.empty:
        console.print("[yellow]No close checklist tasks found.[/yellow]")
        return
    _print_frame("Close Checklist", tasks[["task_id", "status", "owner", "due_date", "category", "task_name", "note"]], max_rows=100)
    summary = close_summary_frame(checklist)
    completion = summary[summary["metric"].eq("completion_rate_pct")]
    if not completion.empty:
        console.print(f"[dim]Completion:[/dim] {completion.iloc[0]['value']}%")


@close_app.command("set-status")
def close_set_status_command(
    task_id: Annotated[str, typer.Option("--task-id", help="Close checklist task ID.")],
    status: Annotated[str, typer.Option("--status", help=f"Status: {', '.join(ALLOWED_CLOSE_STATUSES)}")],
    input_path: Annotated[Path, typer.Option("--input", help="Close checklist directory or JSON file.")] = Path("output/close"),
    owner: Annotated[str, typer.Option("--owner", help="Plain-text owner name or role.")] = "",
    note: Annotated[str, typer.Option("--note", help="Local workflow note.")] = "",
    due_date: Annotated[str, typer.Option("--due-date", help="Optional due date text.")] = "",
) -> None:
    """Update one local close checklist task."""

    try:
        task = update_close_task_status(input_path, task_id=task_id, status=status, owner=owner, note=note, due_date=due_date)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Close task updated:[/green] {task['task_id']} | {task['status']}")


@close_app.command("report")
def close_report_command(
    input_path: Annotated[Path, typer.Option("--input", help="Close checklist directory or JSON file.")] = Path("output/close"),
    output_path: Annotated[Path, typer.Option("--output", help="Close report output directory.")] = Path("output/close_report"),
) -> None:
    """Export a local close checklist report."""

    try:
        artifacts = export_close_report(input_path, output_path)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    _print_success_paths(
        [
            artifacts.html_path,
            artifacts.workbook_path,
            artifacts.csv_path,
            artifacts.markdown_path,
            artifacts.json_path,
        ],
    )


@analyze_app.command("variance")
def analyze_variance_command(
    current_path: Annotated[Path, typer.Option("--current", help="Current generated ReconForge output folder.")],
    previous_path: Annotated[Path, typer.Option("--previous", help="Previous generated ReconForge output folder.")],
    output_path: Annotated[Path, typer.Option("--output", help="Variance output directory.")] = Path("output/variance"),
    amount_threshold: Annotated[float, typer.Option("--amount-threshold", help="Absolute amount threshold for flags.")] = 0.0,
    percent_threshold: Annotated[float, typer.Option("--percent-threshold", help="Percentage threshold for flags.")] = 10.0,
) -> None:
    """Compare two local summary output folders."""

    try:
        artifacts = analyze_variance(
            current_path,
            previous_path,
            output_path,
            amount_threshold=amount_threshold,
            percent_threshold=percent_threshold,
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    _print_success_paths(
        [
            artifacts.workbook_path,
            artifacts.csv_path,
            artifacts.json_path,
            artifacts.html_path,
            artifacts.markdown_path,
        ],
    )


@controls_app.command("matrix")
def controls_matrix_command(
    pack_path: Annotated[Path, typer.Option("--pack", help="Control pack directory.")],
    output_path: Annotated[Path, typer.Option("--output", help="Control matrix output directory.")] = Path("output/control_matrix"),
) -> None:
    """Generate a local control matrix from a rule pack."""

    try:
        artifacts = export_control_matrix(pack_path, output_path)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    _print_success_paths([artifacts.workbook_path, artifacts.csv_path, artifacts.json_path, artifacts.markdown_path])


@compare_app.command("periods", context_settings={"allow_extra_args": True})
def compare_periods_command(
    ctx: typer.Context,
    inputs: Annotated[list[Path], typer.Option("--inputs", help="Generated output folders to compare, in period order.")],
    output_path: Annotated[Path, typer.Option("--output", help="Period comparison output directory.")] = Path("output/period_comparison"),
) -> None:
    """Compare exception outputs from two or more generated periods."""

    period_inputs = [*inputs, *(Path(value) for value in ctx.args)]
    try:
        artifacts = compare_period_outputs(period_inputs, output_path)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Period comparison:[/green] {output_path}")
    _print_success_paths([artifacts.workbook_path, artifacts.html_path, artifacts.json_path, artifacts.markdown_path])


@demo_app.command("run")
def demo_run_command(
    output_path: Annotated[Path, typer.Option("--output", help="Demo output directory.")] = Path("output/demo"),
    input_path: Annotated[Path, typer.Option("--input", help="Sample ERP export directory.")] = Path("examples/sample_data"),
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path("config/reconforge.yml"),
    rules_pack: Annotated[Path, typer.Option("--rules-pack", help="Control pack to run during the demo.")] = Path("control-packs/audit-basic"),
) -> None:
    """Run the local 10-minute sample workflow end to end."""

    issues = validate_input_directory(input_path)
    issue_frame = issues_to_frame(issues)
    error_count = int(issue_frame["severity"].astype(str).eq("error").sum()) if not issue_frame.empty else 0
    if error_count:
        _print_frame("Demo Data Validation Issues", issue_frame)
        console.print("[red]Demo stopped because sample data has validation errors.[/red]")
        raise typer.Exit(code=1)

    config = load_config(_config_option(config_path))
    datasets = read_required_datasets(
        input_path,
        [
            DatasetName.STOCK_MOVES,
            DatasetName.GL_ENTRIES,
            DatasetName.WORK_ORDERS,
            DatasetName.PURCHASE_ORDERS,
            DatasetName.OLD_PARTS_RETURNS,
            DatasetName.INVOICES,
        ],
    )
    output_dir = ensure_output_dir(output_path)
    stock_result = reconcile_stock_gl(datasets[DatasetName.STOCK_MOVES], datasets[DatasetName.GL_ENTRIES], config)
    workorder_result = reconcile_workorders(
        datasets[DatasetName.STOCK_MOVES],
        datasets[DatasetName.WORK_ORDERS],
        datasets[DatasetName.PURCHASE_ORDERS],
        datasets[DatasetName.OLD_PARTS_RETURNS],
        datasets[DatasetName.INVOICES],
        config,
    )
    wip = generate_wip_aging(datasets[DatasetName.WORK_ORDERS], config)

    stock_frames = stock_gl_result_frames(stock_result)
    workorder_frames = workorder_result_frames(workorder_result)
    write_report_frames(stock_frames, output_dir, "stock_gl")
    write_report_frames(workorder_frames, output_dir, "workorders")
    stock_workbook = write_excel_workbook(
        stock_frames,
        output_dir / "stock_gl_reconciliation.xlsx",
        metadata=audit_metadata(config.company_name, "Stock to GL Reconciliation", config.output_currency),
    )
    workorder_workbook = write_excel_workbook(
        workorder_frames,
        output_dir / "workorder_reconciliation.xlsx",
        metadata=audit_metadata(config.company_name, "Work Order Reconciliation", config.output_currency),
    )

    rule_paths = write_rule_results(run_rule_pack(input_path, rules_pack), output_dir / "rules")
    artifacts = generate_management_pack(input_path, output_dir, config, stock_result, workorder_result, wip)

    state_path = output_dir / "review_state.json"
    state = load_review_state(state_path)
    exceptions = collect_exception_frame(output_dir)
    if not exceptions.empty:
        exception_id = str(exceptions.iloc[0]["exception_id"])
        update_review_status(
            exception_id,
            "Under Review",
            state,
            reviewer="Demo Reviewer",
            note="Initial sample review started from the one-command demo.",
            decision_reason="Validate source posting and operational evidence.",
        )
    save_review_state(state_path, state)
    register_path = export_review_register(output_dir, output_dir / "review_register.xlsx")
    evidence_artifacts = generate_evidence_binder(output_dir, output_dir / "evidence")
    client_pack_artifacts = generate_client_pack(output_dir, output_dir / "client_pack")

    paths = [
        artifacts.excel_path,
        output_dir / "executive_report.html",
        output_dir / "dashboard.html",
        artifacts.markdown_path,
        state_path,
        register_path,
        output_dir / "evidence",
        client_pack_artifacts.output_dir,
        stock_workbook,
        workorder_workbook,
        *rule_paths,
    ]
    _print_frame(
        "Demo Workflow",
        pd.DataFrame(
            [
                {"step": "validated_sample_data", "result": f"{len(issue_frame)} validation issues, {error_count} errors"},
                {"step": "stock_to_gl_exceptions", "result": len(stock_result.all_exceptions)},
                {"step": "workorder_exceptions", "result": len(workorder_result.all_exceptions)},
                {"step": "rules_triggered", "result": len(rule_paths)},
                {"step": "evidence_cases", "result": len(evidence_artifacts)},
                {"step": "review_state_entries", "result": len(state)},
            ],
        ),
        max_rows=20,
    )
    _print_success_paths(paths)
    console.print("\n[bold]Next steps[/bold]")
    console.print(f"1. Open dashboard: {output_dir / 'dashboard.html'}")
    console.print(f"2. Open executive report: {output_dir / 'executive_report.html'}")
    console.print(f"3. Open management pack: {output_dir / 'management_pack.xlsx'}")
    console.print(f"4. Open evidence binder: {output_dir / 'evidence' / 'index.html'}")
    console.print(f"5. Review client handoff pack: {client_pack_artifacts.output_dir}")
    console.print(f"6. Run Studio: reconforge studio --input {input_path} --output {output_dir}")
    console.print(f"7. Review or export the register: {register_path}")


@app.command("dashboard")
def dashboard(
    input_path: Annotated[Path, typer.Option("--input", help="Generated output directory to serve.")] = Path("output"),
    host: Annotated[str, typer.Option("--host", help="Bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Bind port.")] = 8501,
) -> None:
    """Start the local dashboard server for generated reports."""

    if not input_path.exists():
        console.print(f"[red]Output directory does not exist:[/red] {input_path}")
        raise typer.Exit(code=1)
    console.print(f"[green]Starting ReconForge dashboard:[/green] http://{host}:{port}")
    uvicorn.run(create_app(input_path), host=host, port=port, log_level="info")


@app.command("studio")
def studio(
    input_path: Annotated[Path, typer.Option("--input", help="ERP input directory for Studio views.")] = Path("examples/sample_data"),
    output_path: Annotated[Path, typer.Option("--output", help="Generated output directory for downloads/evidence.")] = Path("output"),
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path for --require-auth mode.")] = Path("output/reconforge.db"),
    require_auth: Annotated[bool, typer.Option("--require-auth", help="Require local Studio login and RBAC checks.")] = False,
    host: Annotated[str, typer.Option("--host", help="Bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Bind port.")] = 8601,
) -> None:
    """Start ReconForge Studio, a local review workspace."""

    if require_auth:
        try:
            status = database_status(_db_option(db_path))
            if status.pending_versions:
                console.print("[red]ReconForge database has pending migrations. Run 'reconforge db migrate' first.[/red]")
                raise typer.Exit(code=1)
        except DatabaseError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from exc
    console.print(f"[green]Starting ReconForge Studio:[/green] http://{host}:{port}")
    uvicorn.run(
        create_studio_app(input_path, output_path, require_auth=require_auth, db_path=db_path if require_auth else None),
        host=host,
        port=port,
        log_level="info",
    )


@app.command("doctor")
def doctor(
    input_path: Annotated[Path, typer.Option("--input", help="Optional sample data directory to inspect.")] = Path("examples/sample_data"),
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path("config/reconforge.yml"),
    output_path: Annotated[Path, typer.Option("--output", help="Output directory to inspect.")] = Path("output"),
) -> None:
    """Check environment, dependencies, sample data, config, and report output path."""

    checks = []
    checks.append(("Python package", "OK", f"ReconForge ERP {__version__}"))
    try:
        config = load_config(_config_option(config_path))
        checks.append(("Config", "OK", f"{config_path} | {config.company_name}"))
    except ValueError as exc:
        checks.append(("Config", "FAIL", str(exc)))
    checks.append(("Sample data", "OK" if input_path.exists() else "WARN", str(input_path)))
    checks.append(("Output path", "OK", str(ensure_output_dir(output_path))))
    issues = validate_input_directory(input_path) if input_path.exists() else []
    structural_errors = sum(1 for issue in issues if issue.severity == "error")
    warnings = sum(1 for issue in issues if issue.severity == "warning")
    checks.append(("Validation", "OK" if structural_errors == 0 else "FAIL", f"{structural_errors} errors, {warnings} warnings"))

    table = Table(title="ReconForge Doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for check, status, detail in checks:
        style = "green" if status == "OK" else "yellow" if status == "WARN" else "red"
        table.add_row(check, f"[{style}]{status}[/{style}]", detail)
    console.print(table)
    if any(status == "FAIL" for _, status, _ in checks):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
