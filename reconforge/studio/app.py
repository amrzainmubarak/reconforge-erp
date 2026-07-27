"""FastAPI-powered local ReconForge Studio."""

from __future__ import annotations

import logging
from html import escape
from pathlib import Path
from secrets import token_urlsafe
from typing import cast
from urllib.parse import parse_qs

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from reconforge import __version__
from reconforge.api.security import (
    SESSION_TTL_HOURS,
    SessionError,
    authenticate_token,
    create_session,
    revoke_token,
)
from reconforge.auth import AuthRepositoryError, AuthServiceError, LocalAuthService
from reconforge.auth.models import LocalUser
from reconforge.close import close_summary_frame, close_tasks_frame, load_close_checklist
from reconforge.db import DatabaseError, connect
from reconforge.io.generated import GeneratedArtifactError
from reconforge.platform.accounts import AccountReconciliationService
from reconforge.platform.close import CloseManagementService
from reconforge.platform.common import PlatformError, trusted_local_mode
from reconforge.platform.evidence import EvidenceRegistryService
from reconforge.platform.exceptions import ExceptionQueueService
from reconforge.platform.metrics import MetricsService
from reconforge.review.state import (
    ALLOWED_STATUSES,
    load_review_state,
    merge_review_state_with_exceptions,
    save_review_state,
    update_review_status,
)
from reconforge.studio.components import (
    _allowed_choice,
    _bounded_search,
    _evidence_href,
    _form_value,
    _href,
    _layout,
    _login_form,
    _logout_form,
    _message_html,
    _review_update_form,
    _table,
)
from reconforge.studio.data import (
    DOC_SUFFIXES,
    DOWNLOAD_SUFFIXES,
    INVALID_REVIEW_STATUS_MESSAGE,
    AmountFilterInput,
    _evidence_coverage_cards,
    _evidence_download_key,
    _filter_exceptions,
    _filter_form,
    _load_reconciliation,
    _optional_studio_database,
    _read_generated_csv,
    _validate_auth_database,
)
from reconforge.studio.security import STUDIO_SESSION_COOKIE, _safe_denial_page
from reconforge.utils.money import STRICT_FINANCIAL_INPUT_POLICY, InvalidAmountError
from reconforge.utils.safe_paths import build_download_registry, get_registered_download
from reconforge.validators import issues_to_frame, validate_input_directory

logger = logging.getLogger(__name__)


def create_studio_app(
    input_dir: Path | str,
    output_dir: Path | str,
    *,
    require_auth: bool = False,
    db_path: Path | str | None = None,
) -> FastAPI:
    """Create a local ReconForge Studio app."""

    input_path = Path(input_dir)
    output_path = Path(output_dir)
    csrf_token = token_urlsafe(24)
    login_csrf_token = token_urlsafe(24)
    logout_csrf_token = token_urlsafe(24)
    resolved_db_path = _validate_auth_database(db_path) if require_auth else _optional_studio_database(db_path)
    output_registry = build_download_registry(output_path, allowed_suffixes=DOWNLOAD_SUFFIXES)
    evidence_registry = build_download_registry(output_path / "evidence", allowed_suffixes=DOWNLOAD_SUFFIXES, recursive=True)
    docs_registry = build_download_registry(Path("docs"), allowed_suffixes=DOC_SUFFIXES)
    app = FastAPI(title="ReconForge Studio", version=__version__)
    app.state.studio_require_auth = require_auth
    app.state.studio_db_path = resolved_db_path

    auth_nav = (
        f"""
      <span class="nav-spacer"></span>
      <form method="post" action="/logout">
        <input type="hidden" name="csrf_token" value="{escape(logout_csrf_token)}">
        <button class="nav-button" type="submit">Sign Out</button>
      </form>
      """
        if require_auth
        else ""
    )

    def _render(title: str, body: str) -> str:
        return _layout(title, body, auth_nav=auth_nav)

    def _login_page(*, message: str = "", status_code: int = 200) -> HTMLResponse:
        return HTMLResponse(_layout("Studio Sign In", _login_form(login_csrf_token, message=message)), status_code=status_code)

    def _auth_denial(title: str, message: str, *, status_code: int) -> HTMLResponse:
        return _safe_denial_page(title, message, status_code=status_code, auth_nav=auth_nav)

    def _current_user(request: Request) -> LocalUser | None:
        user = getattr(request.state, "studio_user", None)
        return cast(LocalUser, user) if isinstance(user, LocalUser) else None

    def _request_has_permission(request: Request, permission: str) -> bool:
        if not require_auth:
            return True
        user = _current_user(request)
        if user is None or resolved_db_path is None:
            return False
        try:
            connection = connect(resolved_db_path, require_exists=True)
        except DatabaseError:
            logger.warning("Rejected Studio action because the auth database is unavailable")
            return False
        try:
            return LocalAuthService(connection).user_has_permission(username=user.username, permission=permission)
        except (DatabaseError, AuthRepositoryError, AuthServiceError):
            logger.warning("Rejected Studio action after RBAC lookup failure")
            return False
        finally:
            connection.close()

    @app.middleware("http")
    async def require_studio_auth(request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not require_auth:
            return await call_next(request)
        if request.url.path == "/login":
            return await call_next(request)
        token = request.cookies.get(STUDIO_SESSION_COOKIE, "")
        if resolved_db_path is None:
            return _safe_denial_page(
                "Studio authentication unavailable",
                "Studio auth-required mode is not configured with a local database.",
                status_code=503,
            )
        try:
            connection = connect(resolved_db_path, require_exists=True)
        except DatabaseError:
            logger.warning("Rejected Studio request because the auth database is unavailable")
            return _safe_denial_page(
                "Studio authentication unavailable",
                "The local Studio authentication database is unavailable.",
                status_code=503,
            )
        try:
            user = authenticate_token(connection, token=token)
        except (DatabaseError, SessionError, AuthRepositoryError):
            logger.warning("Rejected Studio request with invalid or unavailable session")
            user = None
        finally:
            connection.close()
        if user is None:
            if request.method.upper() == "GET":
                return RedirectResponse("/login", status_code=303)
            return _safe_denial_page("Authentication Required", "Sign in to ReconForge Studio and try again.", status_code=401)
        request.state.studio_user = user
        return await call_next(request)

    @app.middleware("http")
    async def set_studio_actor_context(request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Allow unbound actors only for the explicitly trusted no-auth Studio mode."""

        with trusted_local_mode(not require_auth):
            return await call_next(request)

    def _render_exceptions_page(
        *,
        severity: str = "",
        exception_type: str = "",
        status: str = "",
        source_file: str = "",
        search: str = "",
        min_amount: AmountFilterInput = "0",
        sort: str = "risk_score",
        message: str = "",
        message_type: str = "success",
    ) -> str:
        rec = _load_reconciliation(input_path)
        try:
            review_state = load_review_state(output_path / "review_state.json")
        except GeneratedArtifactError:
            logger.warning("Rejected unsafe local review state")
            review_state = {}
            message = "Review state failed safety validation. The file was not loaded."
            message_type = "error"
        exceptions_frame = merge_review_state_with_exceptions(
            rec["exceptions"],
            review_state,
        )
        selected_status = _allowed_choice(status, list(ALLOWED_STATUSES))
        severity_values = sorted(
            {
                value
                for column in ("severity", "risk_level")
                if column in exceptions_frame.columns
                for value in exceptions_frame[column].astype(str).str.strip()
                if value and str(value).lower() != "nan"
            },
            key=lambda item: str(item),
        )
        exception_values = sorted(set(exceptions_frame.get("exception_type", pd.Series(dtype=str)).astype(str).str.strip()) - {""})
        source_values = sorted(set(exceptions_frame.get("source_file", pd.Series(dtype=str)).astype(str).str.strip()) - {""})
        filtered = _filter_exceptions(
            exceptions_frame,
            severity=_allowed_choice(severity, severity_values),
            exception_type=_allowed_choice(exception_type, exception_values),
            status=selected_status,
            source_file=_allowed_choice(source_file, source_values),
            search=_bounded_search(search),
            min_amount=min_amount,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
            sort=_allowed_choice(sort, ["risk_score", "amount_impact", "updated_at"]) or "risk_score",
        )
        if selected_status:
            reviewed_ids = set(exceptions_frame["exception_id"].astype(str))
            orphan_rows: list[dict[str, object]] = []
            for exception_id, review_entry in review_state.items():
                if str(review_entry.get("status", "")).strip() != selected_status:
                    continue
                if str(exception_id).strip() in reviewed_ids:
                    continue
                orphan_rows.append({column: "" for column in exceptions_frame.columns})
                orphan_rows[-1]["exception_id"] = exception_id
                for field in (
                    "status",
                    "reviewer",
                    "note",
                    "updated_at",
                    "decision_reason",
                    "accepted_risk_reason",
                    "escalation_owner",
                ):
                    orphan_rows[-1][field] = review_entry.get(field, "")
            if orphan_rows:
                filtered = pd.concat(
                    [filtered, pd.DataFrame(orphan_rows, columns=exceptions_frame.columns)],
                    ignore_index=True,
                    sort=False,
                )
        form = _filter_form(exceptions_frame)
        empty_message = "<p>No exceptions match the current filters.</p>" if filtered.empty else ""
        body = (
            "<h2>Exception Review</h2>"
            + _message_html(message, message_type)
            + _review_update_form(csrf_token)
            + form
            + empty_message
            + _table(filtered, limit=100)
        )
        return _render("Exceptions", body)

    @app.get("/login", response_class=HTMLResponse)
    def login_page() -> HTMLResponse:
        if not require_auth:
            return HTMLResponse(_layout("Studio Sign In", "<h2>Studio Sign In</h2><p>Studio is running in trusted local mode.</p>"))
        return _login_page()

    @app.post("/login", response_class=HTMLResponse, response_model=None)
    async def login(request: Request) -> Response:
        if not require_auth:
            return RedirectResponse("/", status_code=303)
        form = parse_qs((await request.body()).decode("utf-8", errors="replace"), keep_blank_values=True)
        if _form_value(form, "csrf_token", max_length=200) != login_csrf_token:
            return _login_page(message="Sign in failed. Refresh Studio and try again.", status_code=400)
        username = _form_value(form, "username", max_length=120)
        password = _form_value(form, "password", max_length=512)
        if resolved_db_path is None:
            return _auth_denial(
                "Studio authentication unavailable",
                "Studio auth-required mode is not configured with a local database.",
                status_code=503,
            )
        try:
            connection = connect(resolved_db_path, require_exists=True)
        except DatabaseError:
            logger.warning("Rejected Studio login because the auth database is unavailable")
            return _auth_denial(
                "Studio authentication unavailable",
                "The local Studio authentication database is unavailable.",
                status_code=503,
            )
        try:
            user = LocalAuthService(connection).authenticate_user(username=username, password=password)
            if user is None:
                logger.warning("Rejected Studio login for invalid or disabled local user")
                return _login_page(message="Invalid username or password.", status_code=401)
            session = create_session(connection, user=user)
        except (DatabaseError, AuthRepositoryError, AuthServiceError, SessionError):
            logger.warning("Rejected Studio login after authentication service failure")
            return _login_page(message="Invalid username or password.", status_code=401)
        finally:
            connection.close()
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            STUDIO_SESSION_COOKIE,
            session.token,
            max_age=SESSION_TTL_HOURS * 60 * 60,
            httponly=True,
            samesite="strict",
        )
        return response

    @app.get("/logout", response_class=HTMLResponse)
    def logout_page() -> HTMLResponse:
        if not require_auth:
            return HTMLResponse(_layout("Sign Out", "<h2>Sign Out</h2><p>Studio is running in trusted local mode.</p>"))
        return HTMLResponse(_render("Sign Out", _logout_form(logout_csrf_token)))

    @app.post("/logout", response_class=HTMLResponse, response_model=None)
    async def logout(request: Request) -> Response:
        if not require_auth:
            return RedirectResponse("/", status_code=303)
        form = parse_qs((await request.body()).decode("utf-8", errors="replace"), keep_blank_values=True)
        if _form_value(form, "csrf_token", max_length=200) != logout_csrf_token:
            return _auth_denial("Sign Out Failed", "Refresh Studio and try again.", status_code=400)
        token = request.cookies.get(STUDIO_SESSION_COOKIE, "")
        if resolved_db_path is not None:
            try:
                connection = connect(resolved_db_path, require_exists=True)
                try:
                    revoke_token(connection, token=token)
                finally:
                    connection.close()
            except (DatabaseError, SessionError):
                logger.warning("Unable to revoke Studio session during logout")
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(STUDIO_SESSION_COOKIE)
        return response

    @app.get("/", response_class=HTMLResponse)
    def overview() -> str:
        rec = _load_reconciliation(input_path)
        exceptions = rec["exceptions"]
        cards = "".join(
            [
                f'<section class="card"><span>Input Folder</span><strong>{escape(str(input_path))}</strong></section>',
                f'<section class="card"><span>Total Exceptions</span><strong>{len(exceptions)}</strong></section>',
                f'<section class="card"><span>Critical Risks</span><strong>{exceptions.get("risk_level", pd.Series(dtype=str)).astype(str).eq("Critical").sum()}</strong></section>',
                f'<section class="card"><span>Open WIP</span><strong>{len(rec["wip"])}</strong></section>',
            ],
        )
        return _render("ReconForge Studio", f"<h2>Overview</h2><div class='grid'>{cards}</div>")

    @app.get("/health", response_class=HTMLResponse)
    def health() -> str:
        files = sorted(input_path.glob("*.csv"))
        rows = [{"file": path.name, "rows": len(_read_generated_csv(path))} for path in files]
        return _render("Dataset Health", "<h2>Dataset Health</h2>" + _table(pd.DataFrame(rows)))

    @app.get("/validation", response_class=HTMLResponse)
    def validation() -> str:
        return _render("Validation", "<h2>Validation Results</h2>" + _table(issues_to_frame(validate_input_directory(input_path))))

    @app.get("/reconciliation", response_class=HTMLResponse)
    def reconciliation() -> str:
        rec = _load_reconciliation(input_path)
        return _render(
            "Reconciliation",
            "<h2>Stock vs GL</h2>"
            + _table(rec["stock"].summary)
            + "<h2>Work Orders</h2>"
            + _table(rec["workorders"].summary),
        )

    @app.get("/exceptions", response_class=HTMLResponse, response_model=None)
    def exceptions(
        severity: str = "",
        exception_type: str = "",
        status: str = "",
        source_file: str = "",
        search: str = "",
        min_amount: str = "0",
        sort: str = "risk_score",
    ) -> str | HTMLResponse:
        try:
            return _render_exceptions_page(
                severity=severity,
                exception_type=exception_type,
                status=status,
                source_file=source_file,
                search=search,
                min_amount=min_amount,
                sort=sort,
            )
        except InvalidAmountError:
            return HTMLResponse(
                _render(
                    "Invalid Exception Filter",
                    "<h2>Invalid Exception Filter</h2>"
                    "<p>Minimum amount must be a finite, non-negative plain decimal value.</p>",
                ),
                status_code=400,
            )

    @app.post("/exceptions/update-review", response_class=HTMLResponse, response_model=None)
    async def update_exception_review(request: Request) -> str | HTMLResponse:
        if not _request_has_permission(request, "reconciliation.review"):
            return _auth_denial(
                "Permission Denied",
                "Your local role does not allow updating exception review status.",
                status_code=403,
            )
        form = parse_qs((await request.body()).decode("utf-8", errors="replace"), keep_blank_values=True)
        if _form_value(form, "csrf_token", max_length=200) != csrf_token:
            return _render_exceptions_page(message="Review update rejected. Refresh Studio and try again.", message_type="error")
        state_path = output_path / "review_state.json"
        try:
            state = load_review_state(state_path)
        except GeneratedArtifactError:
            logger.warning("Rejected review update because local review state failed safety validation")
            return _render_exceptions_page(
                message="Review state failed safety validation. No changes were saved.",
                message_type="error",
            )
        exception_id = _form_value(form, "exception_id", max_length=80)
        status_value = _form_value(form, "status", max_length=40)
        if not _allowed_choice(status_value, list(ALLOWED_STATUSES)):
            logger.warning("Rejected review status update with invalid status")
            return _render_exceptions_page(
                message=INVALID_REVIEW_STATUS_MESSAGE,
                message_type="error",
            )
        try:
            entry = update_review_status(
                exception_id,
                status_value,
                state,
                reviewer=_form_value(form, "reviewer", max_length=120),
                note=_form_value(form, "note", max_length=500),
                decision_reason=_form_value(form, "decision_reason", max_length=500),
                accepted_risk_reason=_form_value(form, "accepted_risk_reason", max_length=500),
                escalation_owner=_form_value(form, "escalation_owner", max_length=120),
            )
        except ValueError:
            logger.warning("Rejected review status update with invalid input")
            return _render_exceptions_page(
                message="Unable to update review status. Please verify your input.",
                message_type="error",
            )
        save_review_state(state_path, state)
        details: list[str] = []
        if entry.get("reviewer"):
            details.append(f"reviewer={entry['reviewer']}")
        if entry.get("note"):
            details.append(f"note={entry['note']}")
        detail_message = f" ({'; '.join(details)})" if details else ""
        return _render_exceptions_page(
            status=entry["status"],
            message=f"Review updated for {entry['exception_id']} as {entry['status']}.{detail_message}",
        )

    @app.get("/rule-results", response_class=HTMLResponse)
    def rule_results() -> str:
        rules_path = output_path / "rules" / "rule_results.csv"
        if not rules_path.exists():
            return _render("Rule Results", "<h2>Rule Results</h2><p>No rule results have been generated yet.</p>")
        frame = _read_generated_csv(
            rules_path,
            companion_path=rules_path.with_suffix(".json"),
            collection_key="results",
        )
        return _render("Rule Results", "<h2>Rule Results</h2>" + _table(frame, limit=100))

    @app.get("/close", response_class=HTMLResponse)
    def close() -> str:
        try:
            checklist = load_close_checklist(output_path / "close")
        except (FileNotFoundError, ValueError):
            return _render("Close", "<h2>Close Checklist</h2><p>No close checklist has been generated yet.</p>")
        summary = close_summary_frame(checklist)
        tasks = close_tasks_frame(checklist)
        return _render("Close", "<h2>Close Checklist</h2>" + _table(summary) + "<h2>Tasks</h2>" + _table(tasks, limit=100))

    @app.get("/variance", response_class=HTMLResponse)
    def variance() -> str:
        variance_path = output_path / "variance" / "variance_analysis.csv"
        frame = _read_generated_csv(
            variance_path,
            companion_path=variance_path.with_suffix(".json"),
            collection_key="variances",
        )
        if frame.empty:
            return _render("Variance", "<h2>Variance Analysis</h2><p>No variance analysis has been generated yet.</p>")
        return _render("Variance", "<h2>Variance Analysis</h2>" + _table(frame, limit=100))

    @app.get("/control-matrix", response_class=HTMLResponse)
    def control_matrix() -> str:
        matrix_path = output_path / "control_matrix" / "control_matrix.csv"
        frame = _read_generated_csv(
            matrix_path,
            companion_path=matrix_path.with_suffix(".json"),
            collection_key="controls",
        )
        if frame.empty:
            return _render("Control Matrix", "<h2>Control Matrix</h2><p>No control matrix has been generated yet.</p>")
        return _render("Control Matrix", "<h2>Control Matrix</h2>" + _table(frame, limit=100))

    @app.get("/risk-matrix", response_class=HTMLResponse)
    def risk_matrix() -> str:
        rec = _load_reconciliation(input_path)
        exceptions_frame = rec["exceptions"]
        if exceptions_frame.empty or "risk_level" not in exceptions_frame.columns:
            return _render("Risk Matrix", "<h2>Risk Matrix</h2><p>No risk data found.</p>")
        group_cols = [column for column in ["risk_level", "exception_type"] if column in exceptions_frame.columns]
        matrix = exceptions_frame.groupby(group_cols, as_index=False).size().rename(columns={"size": "exception_count"})
        return _render("Risk Matrix", "<h2>Risk Matrix</h2>" + _table(matrix, limit=100))

    @app.get("/wip", response_class=HTMLResponse)
    def wip() -> str:
        return _render("WIP Aging", "<h2>WIP Aging</h2>" + _table(_load_reconciliation(input_path)["wip"]))

    @app.get("/control-packs", response_class=HTMLResponse)
    def control_packs() -> str:
        pack_rows = []
        for pack in sorted(Path("control-packs").glob("*/pack.yml")):
            pack_rows.append({"pack": pack.parent.name, "path": str(pack.parent)})
        rules_path = output_path / "rules" / "rule_results.csv"
        body = "<h2>Control Packs</h2>" + _table(pd.DataFrame(pack_rows))
        if rules_path.exists():
            frame = _read_generated_csv(
                rules_path,
                companion_path=rules_path.with_suffix(".json"),
                collection_key="results",
            )
            body += "<h2>Latest Rule Results</h2>" + _table(frame)
        return _render("Control Packs", body)

    @app.get("/evidence", response_class=HTMLResponse)
    def evidence() -> str:
        rec = _load_reconciliation(input_path)
        cards = _evidence_coverage_cards(rec["exceptions"], output_path)
        links = []
        for key in sorted(evidence_registry):
            parts = key.split("/")
            if len(parts) != 2 or not key.endswith("/summary.md"):
                continue
            links.append(f'<li><a href="{_evidence_href(parts[0], parts[1])}">{escape(key)}</a></li>')
        return _render("Evidence", f"<h2>Evidence Binder</h2><div class='grid'>{cards}</div><ul>{''.join(links)}</ul>")

    def _db_unavailable_page(title: str) -> str:
        return _render(title, f"<h2>{escape(title)}</h2><p>No current local DB is available for this Studio page.</p>")

    def _studio_actor(request: Request) -> str:
        user = _current_user(request)
        return user.username if user is not None else "studio-local"

    def _account_action_form() -> str:
        return """
<details class="review-action">
  <summary>Account Reconciliation Action</summary>
  <form class="review-form" method="post" action="/db/accounts/action">
    <label>Reconciliation ID<input name="reconciliation_id" required maxlength="80"></label>
    <label>Action<select name="action"><option>prepare</option><option>submit</option><option>review</option><option>complete</option></select></label>
    <label>Reviewer<input name="reviewer" maxlength="120"></label>
    <button type="submit">Apply</button>
  </form>
</details>
"""

    @app.get("/db/accounts", response_class=HTMLResponse)
    def db_accounts(
        status: str = "",
        owner: str = "",
        period: str = "",
        entity: str = "",
        risk: str = "",
    ) -> str:
        if resolved_db_path is None:
            return _db_unavailable_page("DB Account Reconciliations")
        try:
            connection = connect(resolved_db_path, require_exists=True)
            try:
                records = AccountReconciliationService(connection).list_reconciliations(
                    status=_bounded_search(status),
                    owner=_bounded_search(owner),
                    period_name=_bounded_search(period),
                    entity_code=_bounded_search(entity),
                    risk_rating=_bounded_search(risk),
                )
            finally:
                connection.close()
        except (DatabaseError, PlatformError):
            logger.warning("Unable to render DB account reconciliation page")
            return _render("DB Account Reconciliations", "<h2>DB Account Reconciliations</h2><p>Unable to read local account reconciliations.</p>")
        filters = """
<form class="filters" method="get" action="/db/accounts">
  <label>Status<input name="status"></label>
  <label>Owner<input name="owner"></label>
  <label>Period<input name="period"></label>
  <label>Entity<input name="entity"></label>
  <label>Risk<input name="risk"></label>
  <button type="submit">Apply</button>
</form>
"""
        body = "<h2>DB Account Reconciliations</h2>" + _account_action_form() + filters + _table(pd.DataFrame(records), limit=100)
        return _render("DB Account Reconciliations", body)

    @app.post("/db/accounts/action", response_class=HTMLResponse, response_model=None)
    async def db_accounts_action(request: Request) -> str | Response:
        if resolved_db_path is None:
            return _auth_denial("DB Unavailable", "No current local DB is available for account actions.", status_code=503)
        form = parse_qs((await request.body()).decode("utf-8", errors="replace"), keep_blank_values=True)
        reconciliation_id = _form_value(form, "reconciliation_id", max_length=100)
        action = _form_value(form, "action", max_length=40).lower()
        permission = {
            "prepare": "accounts.prepare",
            "submit": "accounts.prepare",
            "review": "accounts.review",
            "complete": "accounts.complete",
        }.get(action)
        if permission is None or not _request_has_permission(request, permission):
            return _auth_denial("Permission Denied", "Your local role does not allow this account action.", status_code=403)
        try:
            connection = connect(resolved_db_path, require_exists=True)
            try:
                service = AccountReconciliationService(connection)
                actor = _studio_actor(request)
                if action == "prepare":
                    service.prepare(reconciliation_id=reconciliation_id, actor_label=actor)
                elif action == "submit":
                    service.submit(reconciliation_id, actor_label=actor)
                elif action == "review":
                    service.review(reconciliation_id, reviewer=_form_value(form, "reviewer", max_length=120), actor_label=actor)
                elif action == "complete":
                    service.complete(reconciliation_id, actor_label=actor)
            finally:
                connection.close()
        except (DatabaseError, PlatformError):
            logger.warning("Rejected DB account action")
            return _auth_denial("Action Failed", "Unable to apply the account action. Verify the status and permissions.", status_code=400)
        return RedirectResponse("/db/accounts", status_code=303)

    @app.get("/db/close", response_class=HTMLResponse)
    def db_close() -> str:
        if resolved_db_path is None:
            return _db_unavailable_page("DB Close")
        try:
            connection = connect(resolved_db_path, require_exists=True)
            try:
                service = CloseManagementService(connection)
                periods = service.list_periods()
                tasks = service.list_tasks()
            finally:
                connection.close()
        except (DatabaseError, PlatformError):
            logger.warning("Unable to render DB close page")
            return _render("DB Close", "<h2>DB Close</h2><p>Unable to read local close records.</p>")
        return _render("DB Close", "<h2>DB Close</h2><h3>Periods</h3>" + _table(pd.DataFrame(periods)) + "<h3>Tasks</h3>" + _table(pd.DataFrame(tasks), limit=100))

    @app.get("/db/evidence", response_class=HTMLResponse)
    def db_evidence() -> str:
        if resolved_db_path is None:
            return _db_unavailable_page("DB Evidence")
        try:
            connection = connect(resolved_db_path, require_exists=True)
            try:
                service = EvidenceRegistryService(connection)
                evidence_records = service.list_evidence()
                coverage = service.coverage()
            finally:
                connection.close()
        except (DatabaseError, PlatformError):
            logger.warning("Unable to render DB evidence page")
            return _render("DB Evidence", "<h2>DB Evidence</h2><p>Unable to read local evidence registry.</p>")
        cards = (
            f'<section class="card"><span>Coverage</span><strong>{escape(str(coverage["coverage_pct"]))}%</strong></section>'
            f'<section class="card"><span>Requirements</span><strong>{escape(str(coverage["requirement_count"]))}</strong></section>'
        )
        return _render("DB Evidence", f"<h2>DB Evidence</h2><div class='grid'>{cards}</div>" + _table(pd.DataFrame(evidence_records), limit=100))

    @app.get("/db/exceptions", response_class=HTMLResponse)
    def db_exceptions(status: str = "", owner: str = "", risk: str = "") -> str:
        if resolved_db_path is None:
            return _db_unavailable_page("DB Exceptions")
        try:
            connection = connect(resolved_db_path, require_exists=True)
            try:
                records = ExceptionQueueService(connection).list(
                    status=_bounded_search(status),
                    owner=_bounded_search(owner),
                    risk_rating=_bounded_search(risk),
                )
            finally:
                connection.close()
        except (DatabaseError, PlatformError):
            logger.warning("Unable to render DB exceptions page")
            return _render("DB Exceptions", "<h2>DB Exceptions</h2><p>Unable to read local exception queue.</p>")
        filters = """
<form class="filters" method="get" action="/db/exceptions">
  <label>Status<input name="status"></label>
  <label>Owner<input name="owner"></label>
  <label>Risk<input name="risk"></label>
  <button type="submit">Apply</button>
</form>
"""
        return _render("DB Exceptions", "<h2>DB Exceptions</h2>" + filters + _table(pd.DataFrame(records), limit=100))

    @app.get("/db/metrics", response_class=HTMLResponse)
    def db_metrics() -> str:
        if resolved_db_path is None:
            return _db_unavailable_page("DB Metrics")
        try:
            connection = connect(resolved_db_path, require_exists=True)
            try:
                service = MetricsService(connection)
                metrics = service.dashboard()
                lineage = service.lineage()
            finally:
                connection.close()
        except (DatabaseError, PlatformError):
            logger.warning("Unable to render DB metrics page")
            return _render("DB Metrics", "<h2>DB Metrics</h2><p>Unable to read local metrics.</p>")
        return _render("DB Metrics", "<h2>DB Metrics</h2>" + _table(pd.DataFrame(metrics), limit=100) + "<h3>Lineage</h3>" + _table(pd.DataFrame(lineage), limit=100))

    @app.get("/downloads", response_class=HTMLResponse)
    def downloads() -> str:
        links = "".join(f'<li><a href="{_href("/download", key)}">{escape(key)}</a></li>' for key in sorted(output_registry))
        return _render("Downloads", f"<h2>Downloads</h2><ul>{links}</ul>")

    @app.get("/docs", response_class=HTMLResponse)
    def docs() -> str:
        links = "".join(f'<li><a href="{_href("/download-doc", key)}">{escape(key)}</a></li>' for key in sorted(docs_registry))
        return _render("Docs", f"<h2>Documentation</h2><ul>{links}</ul>")

    @app.get("/download/{filename}")
    def download(filename: str) -> FileResponse:
        try:
            path = get_registered_download(output_registry, filename)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid filename") from None
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="File not found") from None
        return FileResponse(path, media_type="application/octet-stream", filename=path.name)

    @app.get("/download/evidence/{case_id}/{filename}")
    def download_evidence(case_id: str, filename: str) -> FileResponse:
        try:
            path = get_registered_download(evidence_registry, _evidence_download_key(case_id, filename))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid filename") from None
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Evidence file not found") from None
        return FileResponse(path, media_type="text/plain", filename=path.name)

    @app.get("/download-doc/{filename}")
    def download_doc(filename: str) -> FileResponse:
        try:
            path = get_registered_download(docs_registry, filename)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid filename") from None
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Doc not found") from None
        return FileResponse(path, media_type="text/markdown", filename=path.name)

    return app
