"""Offline operational posting commands with real password-bound identities."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer

from reconforge.api.finance_posting_contract import (
    project_posted_trial_balance,
    project_posting_effect,
    project_posting_preview,
    project_posting_reversal,
)
from reconforge.api.routes.finance_core import LedgerEntryRequest
from reconforge.application.finance_posting import FinancePostingApplicationService
from reconforge.auth import AuthRepositoryError, AuthServiceError, LocalAuthService
from reconforge.db import DatabaseError, connect
from reconforge.domain.finance_posting import FinancePostingError, PostingActor, canonical_json
from reconforge.platform.common import PlatformError, ServerPrincipal, server_principal_context, trusted_local_mode
from reconforge.platform.finance_core import FinanceCoreService

posting_app = typer.Typer(help="Authenticate, independently review and explicitly post offline financial entries.")
Username = Annotated[str, typer.Option("--username", help="Stored human username; password is requested privately for each command.")]
Database = Annotated[Path, typer.Option("--db", help="Existing migrated local SQLite database.")]
EntryId = Annotated[str, typer.Option("--entry-id")]
Reason = Annotated[str, typer.Option("--reason")]
CommandId = Annotated[str, typer.Option("--command-id", help="Keep this exact identifier and content when retrying an uncertain result.")]
EffectId = Annotated[str, typer.Option("--effect-id")]
Operation = Callable[[sqlite3.Connection, PostingActor], dict[str, Any]]


def _run(db_path: Path, username: str, operation: Operation) -> None:
    connection = None
    try:
        connection = connect(db_path, require_exists=True)
        # Never accept a password in argv, an actor label or a caller-supplied assurance flag.
        password = typer.prompt("Password", hide_input=True, show_default=False)
        auth = LocalAuthService(connection)
        user = auth.authenticate_user(username=username, password=password)
        del password
        if user is None:
            raise FinancePostingError("posting_authentication_failed", "Invalid username or password.")
        permissions = frozenset(auth.roles.user_permissions(user.username))
        actor = PostingActor(user.id, user.username, permissions, step_up_active=True)
        principal = ServerPrincipal(user=user, permissions=permissions, step_up_active=True, step_up_method="password")
        with trusted_local_mode(False), server_principal_context(principal):
            result = operation(connection, actor)
        typer.echo(canonical_json(result))
    except (DatabaseError, AuthRepositoryError, AuthServiceError, PlatformError, FinancePostingError, OSError, ValueError) as exc:
        typer.echo(f"{getattr(exc, 'code', 'posting_command_failed')}: {exc}", err=True)
        raise typer.Exit(1) from exc
    except sqlite3.DatabaseError as exc:
        typer.echo("posting_storage_failed: Local storage rejected the command; no success was acknowledged.", err=True)
        raise typer.Exit(1) from exc
    finally:
        if connection is not None:
            connection.close()


def _service(connection: sqlite3.Connection) -> FinancePostingApplicationService:
    from reconforge.infrastructure.sqlite_finance_posting import SQLiteFinancePostingRepository

    return FinancePostingApplicationService(SQLiteFinancePostingRepository(connection))


def _draft_input(path: Path) -> LedgerEntryRequest:
    if path.suffix.lower() != ".json" or not path.is_file() or path.is_symlink():
        raise FinancePostingError("posting_request_invalid", "Draft input must be a regular local JSON file.")
    with path.open("rb") as source:
        raw = source.read(1_048_577)
    if len(raw) > 1_048_576:
        raise FinancePostingError("posting_request_invalid", "Draft input exceeds the one-MiB limit.")
    payload = LedgerEntryRequest.model_validate_json(raw, strict=True)
    if payload.source_type != "Manual" or not payload.entity_code or not payload.period_id or not payload.journal_code:
        raise FinancePostingError("posting_request_invalid", "Operational draft requires Manual source, legal entity, period and journal.")
    if payload.currency_code:
        raise FinancePostingError("posting_request_invalid", "Currency is captured from the journal; omit currency_code from the draft request.")
    return payload


@posting_app.command("draft")
def draft(
    input_path: Annotated[Path, typer.Option("--input", help="Closed Finance entry JSON; exact debit/credit decimal strings.")],
    username: Username, db_path: Database,
) -> None:
    """Save a Manual draft with the authenticated stable preparer identity."""
    def operation(connection: sqlite3.Connection, actor: PostingActor) -> dict[str, Any]:
        actor.require("finance_core.manage")
        payload = _draft_input(input_path).model_dump()
        payload.pop("currency_code")
        return {"entry": FinanceCoreService(connection).create_entry(**payload, actor_label=actor.username)}
    _run(db_path, username, operation)


@posting_app.command("review")
def review(entry_id: EntryId, reason: Reason, username: Username, db_path: Database) -> None:
    """Independently validate exact content and retain its review digest."""
    def operation(connection: sqlite3.Connection, actor: PostingActor) -> dict[str, Any]:
        actor.require("finance_core.validate")
        FinanceCoreService(connection).validate_entry(entry_id, reason=reason, actor_label=actor.username)
        return {"review": project_posting_preview(_service(connection).preview(entry_id, actor=actor))}
    _run(db_path, username, operation)


@posting_app.command("preview")
def preview(entry_id: EntryId, username: Username, db_path: Database) -> None:
    """Read canonical evidence and current review provenance before posting."""
    _run(db_path, username, lambda connection, actor: {"review": project_posting_preview(_service(connection).preview(entry_id, actor=actor))})


@posting_app.command("post")
def post(
    entry_id: EntryId, command_id: CommandId,
    expected_validation_digest: Annotated[str, typer.Option("--expected-validation-digest")],
    reason: Reason, username: Username, db_path: Database,
) -> None:
    """Create one explicit effect, with exact replay of the same command."""
    _run(db_path, username, lambda connection, actor: {"posting": project_posting_effect(_service(connection).post(
        entry_id, command_id=command_id, expected_validation_digest=expected_validation_digest, reason=reason, actor=actor,
    ))})


@posting_app.command("effect")
def effect(effect_id: EffectId, username: Username, db_path: Database) -> None:
    """Retrieve and verify one retained posting without changing it."""
    _run(db_path, username, lambda connection, actor: {"posting": project_posting_effect(_service(connection).get_effect(effect_id, actor=actor))})


@posting_app.command("reverse")
def reverse(
    effect_id: EffectId, command_id: CommandId,
    entry_number: Annotated[str, typer.Option("--entry-number")],
    period_id: Annotated[str, typer.Option("--period-id")],
    posting_date: Annotated[str, typer.Option("--date")],
    reason: Reason, username: Username, db_path: Database,
) -> None:
    """Prepare a full reversal Draft for separate review and explicit posting."""
    _run(db_path, username, lambda connection, actor: {"reversal": project_posting_reversal(_service(connection).prepare_reversal(
        effect_id, command_id=command_id, entry_number=entry_number, period_id=period_id, posting_date=posting_date, reason=reason, actor=actor,
    ))})


@posting_app.command("trial-balance")
def trial_balance(
    period_id: Annotated[str, typer.Option("--period-id")],
    organization_code: Annotated[str, typer.Option("--organization")],
    entity_code: Annotated[str, typer.Option("--entity")],
    username: Username, db_path: Database,
    workspace: Annotated[str, typer.Option("--workspace")] = "default",
) -> None:
    """Report selected-period net activity and gross turnover with effect drill-down."""
    _run(db_path, username, lambda connection, actor: {"trial_balance": project_posted_trial_balance(_service(connection).posted_trial_balance(
        period_id=period_id, organization_code=organization_code, entity_code=entity_code, workspace=workspace, actor=actor,
    ))})
