"""Governed local chart-of-accounts and balanced ledger-control foundations."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from reconforge.audit import AuditLedgerError
from reconforge.domain.models import utc_now_text
from reconforge.platform.common import (
    PlatformError,
    commit_audited,
    ensure_platform_schema,
    ensure_workspace,
    platform_id,
    require_permission,
)

FINANCE_CORE_READ_PERMISSION = "finance_core.read"
FINANCE_CORE_MANAGE_PERMISSION = "finance_core.manage"
FINANCE_CORE_VALIDATE_PERMISSION = "finance_core.validate"
ACCOUNT_TYPES = ("Asset", "Liability", "Equity", "Income", "Expense", "Off Balance")
NORMAL_BALANCES = ("Debit", "Credit")
DIMENSION_TYPES = ("Cost Center", "Department", "Project", "Custom")
JOURNAL_TYPES = ("General", "Sales", "Purchase", "Bank", "Cash", "Adjustment")
ENTRY_SOURCE_TYPES = ("Manual", "Imported", "Generated")
ENTRY_STATUSES = ("Draft", "Validated", "Voided")
DEFAULT_LIST_LIMIT = 500
MAX_LIST_LIMIT = 100_000
MAX_ENTRY_LINES = 1_000
_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,63}$")
_ENTRY_NUMBER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._/-]{0,63}$")
_AMOUNT_PATTERN = re.compile(r"^(0|[0-9]+)(\.[0-9]+)?$")


@dataclass(frozen=True)
class FinanceCoreSummary:
    """Counts for one workspace's local finance-core records."""

    workspace: str
    charts: int
    accounts: int
    dimensions: int
    dimension_values: int
    journals: int
    draft_entries: int
    validated_entries: int
    voided_entries: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _clean_text(value: object, label: str, *, maximum: int = 160, required: bool = True) -> str:
    raw = str(value).strip() if value is not None else ""
    if any(ord(character) < 32 or ord(character) == 127 for character in raw):
        raise PlatformError(f"{label} must contain printable characters only.")
    text = " ".join(raw.split())
    if required and not text:
        raise PlatformError(f"{label} is required.")
    if len(text) > maximum:
        raise PlatformError(f"{label} must not exceed {maximum} characters.")
    return text


def _code(value: object, label: str) -> str:
    code = _clean_text(value, label, maximum=64).upper()
    if not _CODE_PATTERN.fullmatch(code):
        raise PlatformError(f"{label} must use 1-64 uppercase letters, numbers, dots, underscores, or hyphens.")
    return code


def _entry_number(value: object) -> str:
    number = _clean_text(value, "Entry number", maximum=64).upper()
    if not _ENTRY_NUMBER_PATTERN.fullmatch(number):
        raise PlatformError("Entry number contains unsupported characters.")
    return number


def _choice(value: object, label: str, choices: tuple[str, ...]) -> str:
    candidate = " ".join(_clean_text(value, label, maximum=40).title().split())
    by_lower = {choice.lower(): choice for choice in choices}
    selected = by_lower.get(candidate.lower())
    if selected is None:
        raise PlatformError(f"{label} must be one of: {', '.join(choices)}.")
    return selected


def _iso_date(value: object, label: str) -> date:
    raw = _clean_text(value, label, maximum=10)
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise PlatformError(f"{label} must use YYYY-MM-DD format.") from exc
    if parsed.isoformat() != raw:
        raise PlatformError(f"{label} must use YYYY-MM-DD format.")
    return parsed


def _page(limit: int, offset: int) -> tuple[int, int]:
    if not 1 <= limit <= MAX_LIST_LIMIT:
        raise PlatformError(f"List limit must be between 1 and {MAX_LIST_LIMIT}.")
    if not 0 <= offset <= 10_000_000:
        raise PlatformError("List offset must be between 0 and 10000000.")
    return limit, offset


def _public_record(row: sqlite3.Row) -> dict[str, Any]:
    record = dict(row)
    for field in (
        "active",
        "allow_posting",
        "allow_manual_posting",
        "reconciliation_required",
        "required_on_entries",
    ):
        if field in record:
            record[field] = bool(record[field])
    return record


def _amount_to_minor(value: object, minor_units: int, label: str) -> int:
    if isinstance(value, bool | float):
        raise PlatformError(f"{label} must be supplied as an exact decimal string or integer.")
    raw = str(value).strip() if value is not None else "0"
    if len(raw) > 64 or not _AMOUNT_PATTERN.fullmatch(raw):
        raise PlatformError(f"{label} must be a valid non-negative decimal amount.")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise PlatformError(f"{label} must be a valid non-negative decimal amount.") from exc
    if not amount.is_finite() or amount < 0:
        raise PlatformError(f"{label} must be a valid non-negative decimal amount.")
    scaled = amount * (Decimal(10) ** minor_units)
    if scaled != scaled.to_integral_value():
        raise PlatformError(f"{label} exceeds the currency's {minor_units}-decimal precision.")
    minor = int(scaled)
    if minor > 9_000_000_000_000_000_000:
        raise PlatformError(f"{label} exceeds the supported local amount range.")
    return minor


def _minor_to_text(value: int, minor_units: int) -> str:
    amount = Decimal(value).scaleb(-minor_units)
    return f"{amount:.{minor_units}f}"


class FinanceCoreService:
    """Manage local finance masters and balanced control-ledger entries."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        expected = {
            "charts_of_accounts",
            "accounting_dimensions",
            "accounting_dimension_values",
            "finance_journals",
            "ledger_entries",
            "ledger_lines",
            "ledger_line_dimensions",
        }
        try:
            existing = {
                str(row["name"])
                for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to inspect the local finance-core schema.") from exc
        if not expected <= existing:
            raise PlatformError("Finance-core schema is not initialized. Run 'reconforge db migrate' first.")

    def upsert_chart(
        self,
        *,
        chart_code: str,
        name: str,
        workspace: str = "default",
        organization_code: str = "",
        description: str = "",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Create or update a chart of accounts without changing existing account identities."""

        require_permission(self.connection, actor_label=actor_label, permission=FINANCE_CORE_MANAGE_PERMISSION)
        workspace_name = _clean_text(workspace, "Workspace name")
        workspace_id = ensure_workspace(self.connection, workspace_name)
        code = _code(chart_code, "Chart code")
        organization_id: str | None = None
        normalized_org = ""
        if organization_code.strip():
            organization = self._organization(workspace_id, _code(organization_code, "Organization code"))
            organization_id = str(organization["id"])
            normalized_org = str(organization["organization_code"])
        chart_id = self._default_chart_id(workspace_id) if code == "DEFAULT" else platform_id("COA", workspace_id, code)
        existing_chart = self.connection.execute(
            "SELECT id, organization_id FROM charts_of_accounts WHERE workspace_id = ? AND chart_code = ?",
            (workspace_id, code),
        ).fetchone()
        if existing_chart is not None and existing_chart["organization_id"] != organization_id:
            referenced = self.connection.execute(
                "SELECT 1 FROM finance_journals WHERE chart_id = ? LIMIT 1", (existing_chart["id"],)
            ).fetchone()
            if referenced is not None:
                raise PlatformError("A chart referenced by finance journals cannot change organization scope.")
        if not active:
            in_use = self.connection.execute(
                "SELECT 1 FROM accounts WHERE chart_id = ? AND active = 1 LIMIT 1", (chart_id,)
            ).fetchone()
            if in_use is not None:
                raise PlatformError("Deactivate active accounts before deactivating their chart.")
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO charts_of_accounts (
                    id, workspace_id, organization_id, chart_code, name, description, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, chart_code) DO UPDATE SET
                    organization_id = excluded.organization_id,
                    name = excluded.name,
                    description = excluded.description,
                    active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (
                    chart_id,
                    workspace_id,
                    organization_id,
                    code,
                    _clean_text(name, "Chart name"),
                    _clean_text(description, "Chart description", maximum=500, required=False),
                    int(active),
                    now,
                    now,
                ),
            )
            record = self._chart(workspace_id, code)
            commit_audited(
                self.connection,
                actor_label=actor_label,
                object_type="chart_of_accounts",
                object_id=str(record["id"]),
                action="chart_of_accounts_upserted",
                metadata={"chart_code": code, "organization_code": normalized_org, "active": active},
                emit_outbox=True,
                outbox_payload={"chart_code": code, "organization_code": normalized_org, "active": active},
            )
        except (PlatformError, sqlite3.DatabaseError, AuditLedgerError) as exc:
            self.connection.rollback()
            if isinstance(exc, PlatformError):
                raise
            raise PlatformError("Unable to save the local chart of accounts.") from exc
        return record

    def list_charts(
        self,
        *,
        workspace: str = "default",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        require_permission(self.connection, actor_label=actor_label, permission=FINANCE_CORE_READ_PERMISSION)
        page_limit, page_offset = _page(limit, offset)
        workspace_id = self._workspace_id(workspace)
        if workspace_id is None:
            return []
        try:
            rows = self.connection.execute(
                """
                SELECT charts_of_accounts.*, organizations.organization_code
                FROM charts_of_accounts
                LEFT JOIN organizations ON organizations.id = charts_of_accounts.organization_id
                WHERE charts_of_accounts.workspace_id = ?
                ORDER BY charts_of_accounts.chart_code
                LIMIT ? OFFSET ?
                """,
                (workspace_id, page_limit, page_offset),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local charts of accounts.") from exc
        return [_public_record(row) for row in rows]

    def upsert_account(
        self,
        *,
        account_code: str,
        name: str,
        workspace: str = "default",
        chart_code: str = "DEFAULT",
        parent_account_code: str = "",
        account_type: str = "Asset",
        normal_balance: str = "Debit",
        allow_posting: bool = True,
        allow_manual_posting: bool = True,
        reconciliation_required: bool = False,
        active: bool = True,
        description: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Create or update one governed chart account and enforce an acyclic hierarchy."""

        require_permission(self.connection, actor_label=actor_label, permission=FINANCE_CORE_MANAGE_PERMISSION)
        workspace_name = _clean_text(workspace, "Workspace name")
        workspace_id = ensure_workspace(self.connection, workspace_name)
        chart = self._ensure_chart(workspace_id, _code(chart_code, "Chart code"))
        if not chart["active"]:
            raise PlatformError("Accounts require an active chart of accounts.")
        code = _code(account_code, "Account code")
        selected_type = _choice(account_type, "Account type", ACCOUNT_TYPES)
        selected_balance = _choice(normal_balance, "Normal balance", NORMAL_BALANCES)
        account_id = platform_id("ACC", workspace_id, code)
        existing = self.connection.execute(
            "SELECT id, chart_id FROM accounts WHERE workspace_id = ? AND account_code = ?",
            (workspace_id, code),
        ).fetchone()
        if existing is not None:
            account_id = str(existing["id"])
            if str(existing["chart_id"]) != str(chart["id"]):
                raise PlatformError("An account code cannot be moved between charts in this foundation.")
        parent_id: str | None = None
        if parent_account_code.strip():
            parent = self._account(str(chart["id"]), _code(parent_account_code, "Parent account code"))
            parent_id = str(parent["id"])
            if parent_id == account_id:
                raise PlatformError("An account cannot be its own parent.")
            if existing is not None and self._is_descendant(account_id, parent_id):
                raise PlatformError("Account hierarchy must remain acyclic.")
        if not active:
            referenced = self.connection.execute(
                "SELECT 1 FROM ledger_lines WHERE account_id = ? LIMIT 1", (account_id,)
            ).fetchone()
            if referenced is not None:
                raise PlatformError("Accounts referenced by ledger-control lines cannot be deactivated.")
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO accounts (
                    id, workspace_id, account_code, account_name, created_at, chart_id,
                    parent_account_id, account_type, normal_balance, allow_posting,
                    allow_manual_posting, reconciliation_required, active, description, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, account_code) DO UPDATE SET
                    account_name = excluded.account_name,
                    parent_account_id = excluded.parent_account_id,
                    account_type = excluded.account_type,
                    normal_balance = excluded.normal_balance,
                    allow_posting = excluded.allow_posting,
                    allow_manual_posting = excluded.allow_manual_posting,
                    reconciliation_required = excluded.reconciliation_required,
                    active = excluded.active,
                    description = excluded.description,
                    updated_at = excluded.updated_at
                """,
                (
                    account_id,
                    workspace_id,
                    code,
                    _clean_text(name, "Account name"),
                    now,
                    chart["id"],
                    parent_id,
                    selected_type,
                    selected_balance,
                    int(allow_posting),
                    int(allow_manual_posting),
                    int(reconciliation_required),
                    int(active),
                    _clean_text(description, "Account description", maximum=500, required=False),
                    now,
                ),
            )
            record = self._account(str(chart["id"]), code)
            commit_audited(
                self.connection,
                actor_label=actor_label,
                object_type="financial_account",
                object_id=str(record["id"]),
                action="financial_account_upserted",
                metadata={"account_code": code, "chart_code": chart["chart_code"], "active": active},
                emit_outbox=True,
                outbox_payload={"account_code": code, "chart_code": chart["chart_code"], "active": active},
            )
        except (PlatformError, sqlite3.DatabaseError, AuditLedgerError) as exc:
            self.connection.rollback()
            if isinstance(exc, PlatformError):
                raise
            raise PlatformError("Unable to save the local financial account.") from exc
        return record

    def list_accounts(
        self,
        *,
        workspace: str = "default",
        chart_code: str = "",
        active_only: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        require_permission(self.connection, actor_label=actor_label, permission=FINANCE_CORE_READ_PERMISSION)
        page_limit, page_offset = _page(limit, offset)
        workspace_id = self._workspace_id(workspace)
        if workspace_id is None:
            return []
        query = """
            SELECT accounts.*, charts_of_accounts.chart_code,
                   parent.account_code AS parent_account_code
            FROM accounts
            JOIN charts_of_accounts ON charts_of_accounts.id = accounts.chart_id
            LEFT JOIN accounts AS parent ON parent.id = accounts.parent_account_id
            WHERE accounts.workspace_id = ?
        """
        parameters: list[object] = [workspace_id]
        if chart_code:
            query += " AND charts_of_accounts.chart_code = ?"
            parameters.append(_code(chart_code, "Chart code"))
        if active_only:
            query += " AND accounts.active = 1"
        query += " ORDER BY charts_of_accounts.chart_code, accounts.account_code LIMIT ? OFFSET ?"
        parameters.extend((page_limit, page_offset))
        try:
            rows = self.connection.execute(query, parameters).fetchall()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local financial accounts.") from exc
        return [_public_record(row) for row in rows]

    def upsert_dimension(
        self,
        *,
        dimension_code: str,
        name: str,
        workspace: str = "default",
        organization_code: str = "",
        dimension_type: str = "Custom",
        required_on_entries: bool = False,
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        require_permission(self.connection, actor_label=actor_label, permission=FINANCE_CORE_MANAGE_PERMISSION)
        workspace_id = ensure_workspace(self.connection, _clean_text(workspace, "Workspace name"))
        code = _code(dimension_code, "Dimension code")
        organization_id: str | None = None
        if organization_code.strip():
            organization_id = str(self._organization(workspace_id, _code(organization_code, "Organization code"))["id"])
        dimension_id = platform_id("DIM", workspace_id, code)
        if not active:
            referenced = self.connection.execute(
                """
                SELECT 1 FROM ledger_line_dimensions links
                JOIN accounting_dimension_values values_ ON values_.id = links.dimension_value_id
                WHERE values_.dimension_id = ? LIMIT 1
                """,
                (dimension_id,),
            ).fetchone()
            if referenced is not None:
                raise PlatformError("Dimensions referenced by ledger-control lines cannot be deactivated.")
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO accounting_dimensions (
                    id, workspace_id, organization_id, dimension_code, name, dimension_type,
                    required_on_entries, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, dimension_code) DO UPDATE SET
                    organization_id = excluded.organization_id,
                    name = excluded.name,
                    dimension_type = excluded.dimension_type,
                    required_on_entries = excluded.required_on_entries,
                    active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (
                    dimension_id,
                    workspace_id,
                    organization_id,
                    code,
                    _clean_text(name, "Dimension name"),
                    _choice(dimension_type, "Dimension type", DIMENSION_TYPES),
                    int(required_on_entries),
                    int(active),
                    now,
                    now,
                ),
            )
            record = self._dimension(workspace_id, code)
            commit_audited(
                self.connection,
                actor_label=actor_label,
                object_type="accounting_dimension",
                object_id=str(record["id"]),
                action="accounting_dimension_upserted",
                metadata={"dimension_code": code, "required_on_entries": required_on_entries, "active": active},
                emit_outbox=True,
                outbox_payload={"dimension_code": code, "required_on_entries": required_on_entries, "active": active},
            )
        except (PlatformError, sqlite3.DatabaseError, AuditLedgerError) as exc:
            self.connection.rollback()
            if isinstance(exc, PlatformError):
                raise
            raise PlatformError("Unable to save the local accounting dimension.") from exc
        return record

    def upsert_dimension_value(
        self,
        *,
        dimension_code: str,
        value_code: str,
        name: str,
        workspace: str = "default",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        require_permission(self.connection, actor_label=actor_label, permission=FINANCE_CORE_MANAGE_PERMISSION)
        workspace_id = ensure_workspace(self.connection, _clean_text(workspace, "Workspace name"))
        dimension = self._dimension(workspace_id, _code(dimension_code, "Dimension code"))
        if not dimension["active"]:
            raise PlatformError("Dimension values require an active dimension.")
        code = _code(value_code, "Dimension value code")
        value_id = platform_id("DIMV", dimension["id"], code)
        if not active:
            referenced = self.connection.execute(
                "SELECT 1 FROM ledger_line_dimensions WHERE dimension_value_id = ? LIMIT 1", (value_id,)
            ).fetchone()
            if referenced is not None:
                raise PlatformError("Dimension values referenced by ledger-control lines cannot be deactivated.")
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO accounting_dimension_values (
                    id, dimension_id, value_code, name, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dimension_id, value_code) DO UPDATE SET
                    name = excluded.name,
                    active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (value_id, dimension["id"], code, _clean_text(name, "Dimension value name"), int(active), now, now),
            )
            record = self._dimension_value(str(dimension["id"]), code)
            commit_audited(
                self.connection,
                actor_label=actor_label,
                object_type="accounting_dimension_value",
                object_id=str(record["id"]),
                action="accounting_dimension_value_upserted",
                metadata={"dimension_code": dimension["dimension_code"], "value_code": code, "active": active},
                emit_outbox=True,
                outbox_payload={"dimension_code": dimension["dimension_code"], "value_code": code, "active": active},
            )
        except (PlatformError, sqlite3.DatabaseError, AuditLedgerError) as exc:
            self.connection.rollback()
            if isinstance(exc, PlatformError):
                raise
            raise PlatformError("Unable to save the local accounting dimension value.") from exc
        return record

    def list_dimensions(
        self,
        *,
        workspace: str = "default",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        require_permission(self.connection, actor_label=actor_label, permission=FINANCE_CORE_READ_PERMISSION)
        page_limit, page_offset = _page(limit, offset)
        workspace_id = self._workspace_id(workspace)
        if workspace_id is None:
            return []
        try:
            rows = self.connection.execute(
                """
                SELECT accounting_dimensions.*, organizations.organization_code
                FROM accounting_dimensions
                LEFT JOIN organizations ON organizations.id = accounting_dimensions.organization_id
                WHERE accounting_dimensions.workspace_id = ?
                ORDER BY accounting_dimensions.dimension_code
                LIMIT ? OFFSET ?
                """,
                (workspace_id, page_limit, page_offset),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local accounting dimensions.") from exc
        return [_public_record(row) for row in rows]

    def list_dimension_values(
        self,
        *,
        dimension_code: str = "",
        workspace: str = "default",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        require_permission(self.connection, actor_label=actor_label, permission=FINANCE_CORE_READ_PERMISSION)
        page_limit, page_offset = _page(limit, offset)
        workspace_id = self._workspace_id(workspace)
        if workspace_id is None:
            return []
        query = """
            SELECT accounting_dimension_values.*, accounting_dimensions.dimension_code
            FROM accounting_dimension_values
            JOIN accounting_dimensions ON accounting_dimensions.id = accounting_dimension_values.dimension_id
            WHERE accounting_dimensions.workspace_id = ?
        """
        parameters: list[object] = [workspace_id]
        if dimension_code:
            query += " AND accounting_dimensions.dimension_code = ?"
            parameters.append(_code(dimension_code, "Dimension code"))
        query += (
            " ORDER BY accounting_dimensions.dimension_code, accounting_dimension_values.value_code LIMIT ? OFFSET ?"
        )
        parameters.extend((page_limit, page_offset))
        try:
            rows = self.connection.execute(query, parameters).fetchall()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local accounting dimension values.") from exc
        return [_public_record(row) for row in rows]

    def upsert_journal(
        self,
        *,
        journal_code: str,
        name: str,
        organization_code: str,
        currency_code: str,
        workspace: str = "default",
        chart_code: str = "DEFAULT",
        journal_type: str = "General",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        require_permission(self.connection, actor_label=actor_label, permission=FINANCE_CORE_MANAGE_PERMISSION)
        workspace_id = ensure_workspace(self.connection, _clean_text(workspace, "Workspace name"))
        organization = self._organization(workspace_id, _code(organization_code, "Organization code"))
        if not organization["active"]:
            raise PlatformError("Finance journals require an active organization.")
        chart = self._ensure_chart(workspace_id, _code(chart_code, "Chart code"))
        if chart["organization_id"] is not None and chart["organization_id"] != organization["id"]:
            raise PlatformError("Finance journal organization must match its chart of accounts.")
        currency = self._currency(_code(currency_code, "Currency code"))
        if not currency["active"]:
            raise PlatformError("Finance journals require an active currency reference.")
        code = _code(journal_code, "Journal code")
        journal_id = platform_id("FJ", workspace_id, organization["id"], code)
        existing_journal = self.connection.execute(
            """
            SELECT id, chart_id, currency_code FROM finance_journals
            WHERE workspace_id = ? AND organization_id = ? AND journal_code = ?
            """,
            (workspace_id, organization["id"], code),
        ).fetchone()
        if existing_journal is not None and (
            str(existing_journal["chart_id"]) != str(chart["id"])
            or str(existing_journal["currency_code"]) != str(currency["code"])
        ):
            referenced = self.connection.execute(
                "SELECT 1 FROM ledger_entries WHERE finance_journal_id = ? LIMIT 1",
                (existing_journal["id"],),
            ).fetchone()
            if referenced is not None:
                raise PlatformError("A referenced finance journal cannot change its chart or currency.")
        if not active:
            referenced = self.connection.execute(
                "SELECT 1 FROM ledger_entries WHERE finance_journal_id = ? LIMIT 1", (journal_id,)
            ).fetchone()
            if referenced is not None:
                raise PlatformError("Journals referenced by ledger-control entries cannot be deactivated.")
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO finance_journals (
                    id, workspace_id, organization_id, chart_id, journal_code, name,
                    journal_type, currency_code, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, organization_id, journal_code) DO UPDATE SET
                    chart_id = excluded.chart_id,
                    name = excluded.name,
                    journal_type = excluded.journal_type,
                    currency_code = excluded.currency_code,
                    active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (
                    journal_id,
                    workspace_id,
                    organization["id"],
                    chart["id"],
                    code,
                    _clean_text(name, "Journal name"),
                    _choice(journal_type, "Journal type", JOURNAL_TYPES),
                    currency["code"],
                    int(active),
                    now,
                    now,
                ),
            )
            record = self._journal(workspace_id, str(organization["id"]), code)
            commit_audited(
                self.connection,
                actor_label=actor_label,
                object_type="finance_journal",
                object_id=str(record["id"]),
                action="finance_journal_upserted",
                metadata={
                    "journal_code": code,
                    "organization_code": organization["organization_code"],
                    "active": active,
                },
                emit_outbox=True,
                outbox_payload={
                    "journal_code": code,
                    "organization_code": organization["organization_code"],
                    "active": active,
                },
            )
        except (PlatformError, sqlite3.DatabaseError, AuditLedgerError) as exc:
            self.connection.rollback()
            if isinstance(exc, PlatformError):
                raise
            raise PlatformError("Unable to save the local finance journal.") from exc
        return record

    def list_journals(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        require_permission(self.connection, actor_label=actor_label, permission=FINANCE_CORE_READ_PERMISSION)
        page_limit, page_offset = _page(limit, offset)
        workspace_id = self._workspace_id(workspace)
        if workspace_id is None:
            return []
        query = """
            SELECT finance_journals.*, organizations.organization_code, charts_of_accounts.chart_code
            FROM finance_journals
            JOIN organizations ON organizations.id = finance_journals.organization_id
            JOIN charts_of_accounts ON charts_of_accounts.id = finance_journals.chart_id
            WHERE finance_journals.workspace_id = ?
        """
        parameters: list[object] = [workspace_id]
        if organization_code:
            query += " AND organizations.organization_code = ?"
            parameters.append(_code(organization_code, "Organization code"))
        query += " ORDER BY organizations.organization_code, finance_journals.journal_code LIMIT ? OFFSET ?"
        parameters.extend((page_limit, page_offset))
        try:
            rows = self.connection.execute(query, parameters).fetchall()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local finance journals.") from exc
        return [_public_record(row) for row in rows]

    def create_entry(
        self,
        *,
        entry_number: str,
        organization_code: str,
        entity_code: str,
        period_id: str,
        journal_code: str,
        posting_date: str,
        description: str,
        lines: Sequence[Mapping[str, object]],
        workspace: str = "default",
        external_reference: str = "",
        source_type: str = "Manual",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Create or replace a balanced draft entry using exact currency minor units."""

        require_permission(self.connection, actor_label=actor_label, permission=FINANCE_CORE_MANAGE_PERMISSION)
        workspace_name = _clean_text(workspace, "Workspace name")
        workspace_id = ensure_workspace(self.connection, workspace_name)
        organization = self._organization(workspace_id, _code(organization_code, "Organization code"))
        if not organization["active"]:
            raise PlatformError("Ledger-control entries require an active organization.")
        entity = self._entity(str(organization["id"]), _code(entity_code, "Entity code"))
        if not entity["active"]:
            raise PlatformError("Ledger-control entries require an active legal entity.")
        period = self._period(period_id, workspace_id)
        if str(period["status"]) != "Open":
            raise PlatformError("Ledger-control entries can be created only in an Open fiscal period.")
        posted_on = _iso_date(posting_date, "Posting date")
        period_start = _iso_date(period["start_date"], "Stored period start date")
        period_end = _iso_date(period["end_date"], "Stored period end date")
        if posted_on < period_start or posted_on > period_end:
            raise PlatformError("Posting date must fall inside the selected fiscal period.")
        journal = self._journal(workspace_id, str(organization["id"]), _code(journal_code, "Journal code"))
        if not journal["active"]:
            raise PlatformError("Ledger-control entries require an active finance journal.")
        currency = self._currency(str(journal["currency_code"]))
        if str(entity["currency"]).upper() != str(currency["code"]):
            raise PlatformError("Journal and legal-entity currencies must match in this finance-core version.")
        selected_source = _choice(source_type, "Entry source type", ENTRY_SOURCE_TYPES)
        number = _entry_number(entry_number)
        creator = _clean_text(actor_label or "local-cli", "Actor label")
        if not 2 <= len(lines) <= MAX_ENTRY_LINES:
            raise PlatformError(f"Ledger-control entries require between 2 and {MAX_ENTRY_LINES} lines.")
        required_dimensions = self._required_dimensions(workspace_id, str(organization["id"]))
        prepared_lines: list[dict[str, Any]] = []
        total_debit = 0
        total_credit = 0
        for line_number, line in enumerate(lines, start=1):
            if not isinstance(line, Mapping):
                raise PlatformError("Each ledger line must be an object.")
            account = self._account(str(journal["chart_id"]), _code(line.get("account_code"), "Account code"))
            if not account["active"] or not account["allow_posting"]:
                raise PlatformError("Ledger lines require an active posting-enabled account.")
            if selected_source == "Manual" and not account["allow_manual_posting"]:
                raise PlatformError("Manual entries cannot use an account that blocks manual posting.")
            debit_minor = _amount_to_minor(line.get("debit", "0"), int(currency["minor_units"]), "Line debit")
            credit_minor = _amount_to_minor(line.get("credit", "0"), int(currency["minor_units"]), "Line credit")
            if (debit_minor > 0) == (credit_minor > 0):
                raise PlatformError("Each ledger line must contain exactly one non-zero debit or credit amount.")
            dimension_values = self._prepare_line_dimensions(
                line.get("dimensions", {}),
                workspace_id=workspace_id,
                organization_id=str(organization["id"]),
            )
            missing = set(required_dimensions) - set(dimension_values)
            if missing:
                missing_codes = ", ".join(sorted(required_dimensions[item] for item in missing))
                raise PlatformError(f"Ledger line is missing required dimensions: {missing_codes}.")
            prepared_lines.append(
                {
                    "line_number": line_number,
                    "account_id": account["id"],
                    "description": _clean_text(
                        line.get("description", ""), "Line description", maximum=500, required=False
                    ),
                    "debit_minor": debit_minor,
                    "credit_minor": credit_minor,
                    "dimension_values": tuple(dimension_values.values()),
                }
            )
            total_debit += debit_minor
            total_credit += credit_minor
        if total_debit <= 0 or total_debit != total_credit:
            raise PlatformError("Ledger-control entry debits and credits must balance to a non-zero amount.")
        entry_id = platform_id("GLE", workspace_id, number)
        now = utc_now_text()
        existing = self.connection.execute(
            "SELECT status, created_by, created_at FROM ledger_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if existing is not None and str(existing["status"]) != "Draft":
            raise PlatformError("Only Draft ledger-control entries can be replaced.")
        original_creator = str(existing["created_by"]) if existing is not None else creator
        original_created_at = str(existing["created_at"]) if existing is not None else now
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            if existing is not None:
                self.connection.execute("DELETE FROM ledger_lines WHERE entry_id = ?", (entry_id,))
            self.connection.execute(
                """
                INSERT INTO ledger_entries (
                    id, workspace_id, organization_id, chart_id, legal_entity_id, period_id,
                    finance_journal_id, entry_number, posting_date, currency_code, description,
                    external_reference, source_type, status, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Draft', ?, ?, ?)
                ON CONFLICT(workspace_id, entry_number) DO UPDATE SET
                    organization_id = excluded.organization_id,
                    chart_id = excluded.chart_id,
                    legal_entity_id = excluded.legal_entity_id,
                    period_id = excluded.period_id,
                    finance_journal_id = excluded.finance_journal_id,
                    posting_date = excluded.posting_date,
                    currency_code = excluded.currency_code,
                    description = excluded.description,
                    external_reference = excluded.external_reference,
                    source_type = excluded.source_type,
                    updated_at = excluded.updated_at
                """,
                (
                    entry_id,
                    workspace_id,
                    organization["id"],
                    journal["chart_id"],
                    entity["id"],
                    period["id"],
                    journal["id"],
                    number,
                    posted_on.isoformat(),
                    currency["code"],
                    _clean_text(description, "Entry description", maximum=500),
                    _clean_text(external_reference, "External reference", maximum=160, required=False),
                    selected_source,
                    original_creator,
                    original_created_at,
                    now,
                ),
            )
            for prepared in prepared_lines:
                line_id = platform_id("GLL", entry_id, prepared["line_number"])
                self.connection.execute(
                    """
                    INSERT INTO ledger_lines (
                        id, entry_id, line_number, account_id, description,
                        debit_minor, credit_minor, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        line_id,
                        entry_id,
                        prepared["line_number"],
                        prepared["account_id"],
                        prepared["description"],
                        prepared["debit_minor"],
                        prepared["credit_minor"],
                        now,
                    ),
                )
                for dimension_value_id in prepared["dimension_values"]:
                    self.connection.execute(
                        "INSERT INTO ledger_line_dimensions (line_id, dimension_value_id) VALUES (?, ?)",
                        (line_id, dimension_value_id),
                    )
            stored_entry = self.connection.execute("SELECT * FROM ledger_entries WHERE id = ?", (entry_id,)).fetchone()
            if stored_entry is None:
                raise PlatformError("Unable to recheck the local ledger-control draft.")
            self._validate_entry_integrity(dict(stored_entry))
            commit_audited(
                self.connection,
                actor_label=actor_label,
                object_type="ledger_entry",
                object_id=entry_id,
                action="ledger_entry_draft_saved",
                metadata={
                    "entry_number": number,
                    "line_count": len(prepared_lines),
                    "currency_code": currency["code"],
                    "total_minor": total_debit,
                },
                emit_outbox=True,
                outbox_payload={
                    "entry_number": number,
                    "line_count": len(prepared_lines),
                    "currency_code": currency["code"],
                    "total_minor": total_debit,
                },
            )
        except (PlatformError, AuditLedgerError):
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to save the local ledger-control entry.") from exc
        return self.get_entry(entry_id, actor_label=actor_label)

    def validate_entry(
        self,
        entry_id: str,
        *,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Validate a balanced draft locally without posting anything to a source ERP."""

        actor_user = require_permission(
            self.connection, actor_label=actor_label, permission=FINANCE_CORE_VALIDATE_PERMISSION
        )
        validation_reason = _clean_text(reason, "Validation reason", maximum=500)
        now = utc_now_text()
        validator = _clean_text(actor_label or "local-cli", "Actor label")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            entry = self._entry(entry_id)
            if entry["status"] != "Draft":
                raise PlatformError("Only Draft ledger-control entries can be validated.")
            if actor_user is not None and str(entry["created_by"]) == actor_user.username:
                raise PlatformError("Segregation of duties prevents validating your own ledger-control entry.")
            self._validate_entry_integrity(entry)
            cursor = self.connection.execute(
                """
                UPDATE ledger_entries
                SET status = 'Validated', validated_by = ?, validated_at = ?,
                    validation_reason = ?, updated_at = ?
                WHERE id = ? AND status = 'Draft'
                """,
                (validator, now, validation_reason, now, entry_id),
            )
            if cursor.rowcount != 1:
                raise PlatformError("Ledger-control entry changed concurrently; reload and retry.")
            commit_audited(
                self.connection,
                actor_label=actor_label,
                object_type="ledger_entry",
                object_id=entry_id,
                action="ledger_entry_validated",
                metadata={"entry_number": entry["entry_number"], "reason": validation_reason},
                emit_outbox=True,
                outbox_payload={"entry_number": entry["entry_number"], "reason": validation_reason},
            )
        except (PlatformError, AuditLedgerError):
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to validate the local ledger-control entry.") from exc
        return self.get_entry(entry_id, actor_label=actor_label)

    def void_entry(
        self,
        entry_id: str,
        *,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Void validated local control metadata while preserving immutable lines."""

        require_permission(self.connection, actor_label=actor_label, permission=FINANCE_CORE_VALIDATE_PERMISSION)
        entry = self._entry(entry_id)
        if entry["status"] != "Validated":
            raise PlatformError("Only Validated ledger-control entries can be voided.")
        valuation_table = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'inventory_valuation_documents'"
        ).fetchone()
        approved_valuation = None
        if valuation_table is not None:
            approved_valuation = self.connection.execute(
                """
                SELECT valuation_number FROM inventory_valuation_documents
                WHERE finance_entry_id = ? AND status = 'Approved' LIMIT 1
                """,
                (entry_id,),
            ).fetchone()
        if approved_valuation is not None:
            raise PlatformError(
                "Approved inventory valuation "
                f"{approved_valuation['valuation_number']} must be reversed before voiding its Finance Core entry."
            )
        reversal_table = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'inventory_valuation_reversals'"
        ).fetchone()
        approved_reversal = None
        if reversal_table is not None:
            approved_reversal = self.connection.execute(
                """
                SELECT reversal_number FROM inventory_valuation_reversals
                WHERE finance_entry_id = ? AND status = 'Approved' LIMIT 1
                """,
                (entry_id,),
            ).fetchone()
        if approved_reversal is not None:
            raise PlatformError(
                "Approved inventory valuation reversal "
                f"{approved_reversal['reversal_number']} preserves this Finance Core entry as evidence."
            )
        void_reason = _clean_text(reason, "Void reason", maximum=500)
        now = utc_now_text()
        actor = _clean_text(actor_label or "local-cli", "Actor label")
        try:
            cursor = self.connection.execute(
                """
                UPDATE ledger_entries
                SET status = 'Voided', voided_by = ?, voided_at = ?, void_reason = ?, updated_at = ?
                WHERE id = ? AND status = 'Validated'
                """,
                (actor, now, void_reason, now, entry_id),
            )
            if cursor.rowcount != 1:
                raise PlatformError("Ledger-control entry changed concurrently; reload and retry.")
            commit_audited(
                self.connection,
                actor_label=actor_label,
                object_type="ledger_entry",
                object_id=entry_id,
                action="ledger_entry_voided",
                metadata={"entry_number": entry["entry_number"], "reason": void_reason},
                emit_outbox=True,
                outbox_payload={"entry_number": entry["entry_number"], "reason": void_reason},
            )
        except (PlatformError, AuditLedgerError):
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to void the local ledger-control entry.") from exc
        return self.get_entry(entry_id, actor_label=actor_label)

    def get_entry(self, entry_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        require_permission(self.connection, actor_label=actor_label, permission=FINANCE_CORE_READ_PERMISSION)
        entry = self._entry(entry_id)
        currency = self._currency(str(entry["currency_code"]))
        try:
            lines = self.connection.execute(
                """
                SELECT ledger_lines.*, accounts.account_code, accounts.account_name
                FROM ledger_lines
                JOIN accounts ON accounts.id = ledger_lines.account_id
                WHERE ledger_lines.entry_id = ?
                ORDER BY ledger_lines.line_number
                """,
                (entry_id,),
            ).fetchall()
            dimension_rows = self.connection.execute(
                """
                SELECT links.line_id, dimensions.dimension_code, values_.value_code, values_.name
                FROM ledger_line_dimensions links
                JOIN accounting_dimension_values values_ ON values_.id = links.dimension_value_id
                JOIN accounting_dimensions dimensions ON dimensions.id = values_.dimension_id
                JOIN ledger_lines ON ledger_lines.id = links.line_id
                WHERE ledger_lines.entry_id = ?
                ORDER BY links.line_id, dimensions.dimension_code
                """,
                (entry_id,),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read local ledger-control lines.") from exc
        dimensions_by_line: dict[str, dict[str, str]] = {}
        for row in dimension_rows:
            dimensions_by_line.setdefault(str(row["line_id"]), {})[str(row["dimension_code"])] = str(row["value_code"])
        public_lines: list[dict[str, Any]] = []
        total_debit = 0
        total_credit = 0
        minor_units = int(currency["minor_units"])
        for row in lines:
            record = dict(row)
            total_debit += int(record["debit_minor"])
            total_credit += int(record["credit_minor"])
            record["debit"] = _minor_to_text(int(record["debit_minor"]), minor_units)
            record["credit"] = _minor_to_text(int(record["credit_minor"]), minor_units)
            record["dimensions"] = dimensions_by_line.get(str(record["id"]), {})
            public_lines.append(record)
        result = dict(entry)
        result["currency_minor_units"] = minor_units
        result["total_debit_minor"] = total_debit
        result["total_credit_minor"] = total_credit
        result["total_debit"] = _minor_to_text(total_debit, minor_units)
        result["total_credit"] = _minor_to_text(total_credit, minor_units)
        result["balanced"] = total_debit > 0 and total_debit == total_credit and len(public_lines) >= 2
        result["lines"] = public_lines
        return result

    def list_entries(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        entity_code: str = "",
        period_id: str = "",
        status: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        require_permission(self.connection, actor_label=actor_label, permission=FINANCE_CORE_READ_PERMISSION)
        page_limit, page_offset = _page(limit, offset)
        workspace_id = self._workspace_id(workspace)
        if workspace_id is None:
            return []
        query = """
            SELECT ledger_entries.*, organizations.organization_code, legal_entities.entity_code,
                   periods.name AS period_name, finance_journals.journal_code,
                   charts_of_accounts.chart_code,
                   COALESCE(lines.line_count, 0) AS line_count,
                   COALESCE(lines.total_debit_minor, 0) AS total_debit_minor,
                   COALESCE(lines.total_credit_minor, 0) AS total_credit_minor
            FROM ledger_entries
            JOIN organizations ON organizations.id = ledger_entries.organization_id
            JOIN legal_entities ON legal_entities.id = ledger_entries.legal_entity_id
            JOIN periods ON periods.id = ledger_entries.period_id
            JOIN finance_journals ON finance_journals.id = ledger_entries.finance_journal_id
            JOIN charts_of_accounts ON charts_of_accounts.id = ledger_entries.chart_id
            LEFT JOIN (
                SELECT entry_id, COUNT(*) AS line_count, SUM(debit_minor) AS total_debit_minor,
                       SUM(credit_minor) AS total_credit_minor
                FROM ledger_lines GROUP BY entry_id
            ) AS lines ON lines.entry_id = ledger_entries.id
            WHERE ledger_entries.workspace_id = ?
        """
        parameters: list[object] = [workspace_id]
        if organization_code:
            query += " AND organizations.organization_code = ?"
            parameters.append(_code(organization_code, "Organization code"))
        if entity_code:
            query += " AND legal_entities.entity_code = ?"
            parameters.append(_code(entity_code, "Entity code"))
        if period_id:
            query += " AND ledger_entries.period_id = ?"
            parameters.append(_clean_text(period_id, "Fiscal-period identifier", maximum=160))
        if status:
            query += " AND ledger_entries.status = ?"
            parameters.append(_choice(status, "Entry status", ENTRY_STATUSES))
        query += " ORDER BY ledger_entries.posting_date DESC, ledger_entries.entry_number LIMIT ? OFFSET ?"
        parameters.extend((page_limit, page_offset))
        try:
            return [dict(row) for row in self.connection.execute(query, parameters).fetchall()]
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local ledger-control entries.") from exc

    def trial_balance(
        self,
        *,
        period_id: str,
        organization_code: str,
        entity_code: str,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, object]:
        """Aggregate validated local ledger-control lines for one entity and period."""

        require_permission(self.connection, actor_label=actor_label, permission=FINANCE_CORE_READ_PERMISSION)
        workspace_id = self._workspace_id(workspace)
        if workspace_id is None:
            raise PlatformError("Workspace reference was not found.")
        organization = self._organization(workspace_id, _code(organization_code, "Organization code"))
        entity = self._entity(str(organization["id"]), _code(entity_code, "Entity code"))
        period = self._period(period_id, workspace_id)
        currency = self._currency(str(entity["currency"]).upper())
        try:
            rows = self.connection.execute(
                """
                SELECT accounts.account_code, accounts.account_name, accounts.account_type,
                       accounts.normal_balance, SUM(ledger_lines.debit_minor) AS debit_minor,
                       SUM(ledger_lines.credit_minor) AS credit_minor
                FROM ledger_lines
                JOIN ledger_entries ON ledger_entries.id = ledger_lines.entry_id
                JOIN accounts ON accounts.id = ledger_lines.account_id
                WHERE ledger_entries.workspace_id = ?
                  AND ledger_entries.organization_id = ?
                  AND ledger_entries.legal_entity_id = ?
                  AND ledger_entries.period_id = ?
                  AND ledger_entries.status = 'Validated'
                GROUP BY accounts.id, accounts.account_code, accounts.account_name,
                         accounts.account_type, accounts.normal_balance
                ORDER BY accounts.account_code
                """,
                (workspace_id, organization["id"], entity["id"], period["id"]),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to compute the local ledger-control trial balance.") from exc
        minor_units = int(currency["minor_units"])
        records: list[dict[str, object]] = []
        total_debit = 0
        total_credit = 0
        for row in rows:
            debit_minor = int(row["debit_minor"] or 0)
            credit_minor = int(row["credit_minor"] or 0)
            total_debit += debit_minor
            total_credit += credit_minor
            balance_minor = debit_minor - credit_minor
            records.append(
                {
                    "account_code": row["account_code"],
                    "account_name": row["account_name"],
                    "account_type": row["account_type"],
                    "normal_balance": row["normal_balance"],
                    "debit_minor": debit_minor,
                    "credit_minor": credit_minor,
                    "balance_minor": balance_minor,
                    "debit": _minor_to_text(debit_minor, minor_units),
                    "credit": _minor_to_text(credit_minor, minor_units),
                    "balance": _minor_to_text(balance_minor, minor_units),
                }
            )
        return {
            "schema_version": 1,
            "source": {"kind": "local-ledger-control", "local_first": True, "external_calls": False},
            "workspace": _clean_text(workspace, "Workspace name"),
            "organization_code": organization["organization_code"],
            "entity_code": entity["entity_code"],
            "period_id": period["id"],
            "period_name": period["name"],
            "currency_code": currency["code"],
            "currency_minor_units": minor_units,
            "totals": {
                "debit_minor": total_debit,
                "credit_minor": total_credit,
                "balanced": total_debit == total_credit,
                "debit": _minor_to_text(total_debit, minor_units),
                "credit": _minor_to_text(total_credit, minor_units),
            },
            "accounts": records,
        }

    def summary(self, *, workspace: str = "default", actor_label: str = "local-cli") -> FinanceCoreSummary:
        require_permission(self.connection, actor_label=actor_label, permission=FINANCE_CORE_READ_PERMISSION)
        workspace_name = _clean_text(workspace, "Workspace name")
        workspace_id = self._workspace_id(workspace_name)
        if workspace_id is None:
            return FinanceCoreSummary(workspace_name, 0, 0, 0, 0, 0, 0, 0, 0)
        try:
            row = self.connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM charts_of_accounts WHERE workspace_id = ?) AS charts,
                    (SELECT COUNT(*) FROM accounts WHERE workspace_id = ?) AS accounts,
                    (SELECT COUNT(*) FROM accounting_dimensions WHERE workspace_id = ?) AS dimensions,
                    (SELECT COUNT(*) FROM accounting_dimension_values values_
                     JOIN accounting_dimensions dimensions ON dimensions.id = values_.dimension_id
                     WHERE dimensions.workspace_id = ?) AS dimension_values,
                    (SELECT COUNT(*) FROM finance_journals WHERE workspace_id = ?) AS journals,
                    (SELECT COUNT(*) FROM ledger_entries WHERE workspace_id = ? AND status = 'Draft') AS drafts,
                    (SELECT COUNT(*) FROM ledger_entries WHERE workspace_id = ? AND status = 'Validated') AS validated,
                    (SELECT COUNT(*) FROM ledger_entries WHERE workspace_id = ? AND status = 'Voided') AS voided
                """,
                (workspace_id,) * 8,
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to summarize local finance-core records.") from exc
        if row is None:
            raise PlatformError("Unable to summarize local finance-core records.")
        return FinanceCoreSummary(
            workspace_name,
            int(row["charts"]),
            int(row["accounts"]),
            int(row["dimensions"]),
            int(row["dimension_values"]),
            int(row["journals"]),
            int(row["drafts"]),
            int(row["validated"]),
            int(row["voided"]),
        )

    def snapshot(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, object]:
        """Return a bounded, path-free local finance-core contract."""

        workspace_name = _clean_text(workspace, "Workspace name")
        summary = self.summary(workspace=workspace_name, actor_label=actor_label)
        counts = (
            summary.charts,
            summary.accounts,
            summary.dimensions,
            summary.dimension_values,
            summary.journals,
            summary.draft_entries + summary.validated_entries + summary.voided_entries,
        )
        if any(count > MAX_LIST_LIMIT for count in counts):
            raise PlatformError(f"Finance-core snapshot is limited to {MAX_LIST_LIMIT} records per collection.")
        return {
            "schema_version": 1,
            "generated_at": utc_now_text(),
            "source": {"kind": "local-finance-core", "local_first": True, "external_calls": False},
            "workspace": workspace_name,
            "summary": summary.to_dict(),
            "charts": self.list_charts(workspace=workspace_name, limit=MAX_LIST_LIMIT, actor_label=actor_label),
            "accounts": self.list_accounts(workspace=workspace_name, limit=MAX_LIST_LIMIT, actor_label=actor_label),
            "dimensions": self.list_dimensions(workspace=workspace_name, limit=MAX_LIST_LIMIT, actor_label=actor_label),
            "dimension_values": self.list_dimension_values(
                workspace=workspace_name, limit=MAX_LIST_LIMIT, actor_label=actor_label
            ),
            "journals": self.list_journals(workspace=workspace_name, limit=MAX_LIST_LIMIT, actor_label=actor_label),
            "entries": self.list_entries(workspace=workspace_name, limit=MAX_LIST_LIMIT, actor_label=actor_label),
        }

    def _validate_entry_integrity(self, entry: dict[str, Any]) -> None:
        period = self._period(str(entry["period_id"]), str(entry["workspace_id"]))
        if period["status"] != "Open":
            raise PlatformError("Ledger-control entries can be validated only while their fiscal period is Open.")
        posted_on = _iso_date(entry["posting_date"], "Stored posting date")
        if (
            not _iso_date(period["start_date"], "Stored period start date")
            <= posted_on
            <= _iso_date(period["end_date"], "Stored period end date")
        ):
            raise PlatformError("Posting date must remain inside the selected fiscal period.")
        try:
            scope = self.connection.execute(
                """
                SELECT organizations.active AS organization_active,
                       legal_entities.active AS entity_active,
                       finance_journals.active AS journal_active,
                       charts_of_accounts.active AS chart_active,
                       currencies.active AS currency_active,
                       legal_entities.currency AS entity_currency,
                       finance_journals.currency_code AS journal_currency,
                       finance_journals.organization_id AS journal_organization_id,
                       finance_journals.chart_id AS journal_chart_id
                FROM ledger_entries
                JOIN organizations ON organizations.id = ledger_entries.organization_id
                JOIN legal_entities ON legal_entities.id = ledger_entries.legal_entity_id
                JOIN finance_journals ON finance_journals.id = ledger_entries.finance_journal_id
                JOIN charts_of_accounts ON charts_of_accounts.id = ledger_entries.chart_id
                JOIN currencies ON currencies.code = ledger_entries.currency_code
                WHERE ledger_entries.id = ?
                """,
                (entry["id"],),
            ).fetchone()
            totals = self.connection.execute(
                """
                SELECT COUNT(*) AS line_count, COALESCE(SUM(debit_minor), 0) AS debit_minor,
                       COALESCE(SUM(credit_minor), 0) AS credit_minor
                FROM ledger_lines WHERE entry_id = ?
                """,
                (entry["id"],),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to verify local ledger-control entry totals and scope.") from exc
        if (
            scope is None
            or not bool(scope["organization_active"])
            or not bool(scope["entity_active"])
            or not bool(scope["journal_active"])
            or not bool(scope["chart_active"])
            or not bool(scope["currency_active"])
            or str(scope["entity_currency"]).upper() != str(entry["currency_code"])
            or str(scope["journal_currency"]) != str(entry["currency_code"])
            or str(scope["journal_organization_id"]) != str(entry["organization_id"])
            or str(scope["journal_chart_id"]) != str(entry["chart_id"])
        ):
            raise PlatformError("Ledger-control entry contains an inactive or inconsistent finance reference.")
        if (
            totals is None
            or int(totals["line_count"]) < 2
            or int(totals["debit_minor"]) <= 0
            or int(totals["debit_minor"]) != int(totals["credit_minor"])
        ):
            raise PlatformError("Ledger-control entry must contain at least two balanced non-zero lines.")
        try:
            invalid_account = self.connection.execute(
                """
                SELECT 1 FROM ledger_lines
                JOIN accounts ON accounts.id = ledger_lines.account_id
                WHERE ledger_lines.entry_id = ?
                  AND (accounts.chart_id <> ? OR accounts.active = 0 OR accounts.allow_posting = 0
                       OR (? = 'Manual' AND accounts.allow_manual_posting = 0))
                LIMIT 1
                """,
                (entry["id"], entry["chart_id"], entry["source_type"]),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to verify local ledger-control entry accounts.") from exc
        if invalid_account is not None:
            raise PlatformError("Ledger-control entry contains an inactive or posting-restricted account.")
        try:
            invalid_dimension = self.connection.execute(
                """
                SELECT 1 FROM ledger_line_dimensions links
                JOIN ledger_lines lines ON lines.id = links.line_id
                JOIN accounting_dimension_values values_ ON values_.id = links.dimension_value_id
                JOIN accounting_dimensions dimensions ON dimensions.id = values_.dimension_id
                WHERE lines.entry_id = ?
                  AND (values_.active = 0 OR dimensions.active = 0
                       OR dimensions.workspace_id <> ?
                       OR (dimensions.organization_id IS NOT NULL AND dimensions.organization_id <> ?))
                LIMIT 1
                """,
                (entry["id"], entry["workspace_id"], entry["organization_id"]),
            ).fetchone()
            missing_dimension = self.connection.execute(
                """
                SELECT 1
                FROM ledger_lines lines
                CROSS JOIN accounting_dimensions dimensions
                WHERE lines.entry_id = ?
                  AND dimensions.workspace_id = ?
                  AND dimensions.active = 1
                  AND dimensions.required_on_entries = 1
                  AND (dimensions.organization_id IS NULL OR dimensions.organization_id = ?)
                  AND NOT EXISTS (
                      SELECT 1 FROM ledger_line_dimensions links
                      JOIN accounting_dimension_values values_ ON values_.id = links.dimension_value_id
                      WHERE links.line_id = lines.id AND values_.dimension_id = dimensions.id
                  )
                LIMIT 1
                """,
                (entry["id"], entry["workspace_id"], entry["organization_id"]),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to verify local ledger-control entry dimensions.") from exc
        if invalid_dimension is not None:
            raise PlatformError("Ledger-control entry contains an inactive or cross-scope accounting dimension.")
        if missing_dimension is not None:
            raise PlatformError("Ledger-control entry is missing a required accounting dimension.")

    def _prepare_line_dimensions(
        self,
        raw: object,
        *,
        workspace_id: str,
        organization_id: str,
    ) -> dict[str, str]:
        if raw is None:
            return {}
        if not isinstance(raw, Mapping):
            raise PlatformError("Ledger line dimensions must be an object of dimension and value codes.")
        if len(raw) > 20:
            raise PlatformError("Ledger lines support at most 20 dimension assignments.")
        prepared: dict[str, str] = {}
        for raw_dimension_code, raw_value_code in raw.items():
            dimension = self._dimension(workspace_id, _code(raw_dimension_code, "Dimension code"))
            if not dimension["active"]:
                raise PlatformError("Ledger lines require active accounting dimensions.")
            if dimension["organization_id"] is not None and dimension["organization_id"] != organization_id:
                raise PlatformError("Ledger line dimension belongs to a different organization.")
            value = self._dimension_value(str(dimension["id"]), _code(raw_value_code, "Dimension value code"))
            if not value["active"]:
                raise PlatformError("Ledger lines require active accounting dimension values.")
            prepared[str(dimension["id"])] = str(value["id"])
        return prepared

    def _required_dimensions(self, workspace_id: str, organization_id: str) -> dict[str, str]:
        try:
            rows = self.connection.execute(
                """
                SELECT id, dimension_code FROM accounting_dimensions
                WHERE workspace_id = ? AND active = 1 AND required_on_entries = 1
                  AND (organization_id IS NULL OR organization_id = ?)
                """,
                (workspace_id, organization_id),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read required accounting dimensions.") from exc
        return {str(row["id"]): str(row["dimension_code"]) for row in rows}

    def _is_descendant(self, account_id: str, proposed_parent_id: str) -> bool:
        try:
            row = self.connection.execute(
                """
                WITH RECURSIVE descendants(id) AS (
                    SELECT id FROM accounts WHERE parent_account_id = ?
                    UNION ALL
                    SELECT accounts.id FROM accounts
                    JOIN descendants ON accounts.parent_account_id = descendants.id
                )
                SELECT 1 FROM descendants WHERE id = ? LIMIT 1
                """,
                (account_id, proposed_parent_id),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to validate the account hierarchy.") from exc
        return row is not None

    @staticmethod
    def _default_chart_id(workspace_id: str) -> str:
        return f"COA-{workspace_id}"

    def _ensure_chart(self, workspace_id: str, chart_code: str) -> dict[str, Any]:
        if chart_code == "DEFAULT":
            now = utc_now_text()
            exists = self.connection.execute(
                "SELECT 1 FROM charts_of_accounts WHERE workspace_id = ? AND chart_code = 'DEFAULT'",
                (workspace_id,),
            ).fetchone()
            if exists is None:
                had_transaction = self.connection.in_transaction
                try:
                    self.connection.execute(
                        """
                        INSERT INTO charts_of_accounts (
                            id, workspace_id, organization_id, chart_code, name, description,
                            active, created_at, updated_at
                        ) VALUES (?, ?, NULL, 'DEFAULT', 'Default chart of accounts',
                            'Shared local chart for compatibility workflows.', 1, ?, ?)
                        """,
                        (self._default_chart_id(workspace_id), workspace_id, now, now),
                    )
                    if not had_transaction:
                        self.connection.commit()
                except sqlite3.DatabaseError as exc:
                    if self.connection.in_transaction:
                        self.connection.rollback()
                    raise PlatformError("Unable to prepare the default chart of accounts.") from exc
        return self._chart(workspace_id, chart_code)

    def _workspace_id(self, workspace: str) -> str | None:
        name = _clean_text(workspace, "Workspace name")
        workspace_id = platform_id("WS", name)
        try:
            row = self.connection.execute("SELECT id FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local workspace reference.") from exc
        return str(row["id"]) if row is not None else None

    def _organization(self, workspace_id: str, organization_code: str) -> dict[str, Any]:
        try:
            row = self.connection.execute(
                "SELECT * FROM organizations WHERE workspace_id = ? AND organization_code = ?",
                (workspace_id, organization_code),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local organization reference.") from exc
        if row is None:
            raise PlatformError("Organization reference was not found in the selected workspace.")
        return _public_record(row)

    def _chart(self, workspace_id: str, chart_code: str) -> dict[str, Any]:
        try:
            row = self.connection.execute(
                "SELECT * FROM charts_of_accounts WHERE workspace_id = ? AND chart_code = ?",
                (workspace_id, chart_code),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local chart of accounts.") from exc
        if row is None:
            raise PlatformError("Chart of accounts was not found in the selected workspace.")
        return _public_record(row)

    def _account(self, chart_id: str, account_code: str) -> dict[str, Any]:
        try:
            row = self.connection.execute(
                "SELECT * FROM accounts WHERE chart_id = ? AND account_code = ?", (chart_id, account_code)
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local financial account.") from exc
        if row is None:
            raise PlatformError("Financial account was not found in the selected chart.")
        return _public_record(row)

    def _dimension(self, workspace_id: str, dimension_code: str) -> dict[str, Any]:
        try:
            row = self.connection.execute(
                "SELECT * FROM accounting_dimensions WHERE workspace_id = ? AND dimension_code = ?",
                (workspace_id, dimension_code),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local accounting dimension.") from exc
        if row is None:
            raise PlatformError("Accounting dimension was not found in the selected workspace.")
        return _public_record(row)

    def _dimension_value(self, dimension_id: str, value_code: str) -> dict[str, Any]:
        try:
            row = self.connection.execute(
                "SELECT * FROM accounting_dimension_values WHERE dimension_id = ? AND value_code = ?",
                (dimension_id, value_code),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local accounting dimension value.") from exc
        if row is None:
            raise PlatformError("Accounting dimension value was not found.")
        return _public_record(row)

    def _currency(self, currency_code: str) -> dict[str, Any]:
        try:
            row = self.connection.execute("SELECT * FROM currencies WHERE code = ?", (currency_code,)).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local currency reference.") from exc
        if row is None:
            raise PlatformError("Currency reference was not found.")
        return _public_record(row)

    def _entity(self, organization_id: str, entity_code: str) -> dict[str, Any]:
        try:
            row = self.connection.execute(
                "SELECT * FROM legal_entities WHERE organization_id = ? AND entity_code = ?",
                (organization_id, entity_code),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local legal-entity reference.") from exc
        if row is None:
            raise PlatformError("Legal-entity reference was not found in the selected organization.")
        return _public_record(row)

    def _period(self, period_id: str, workspace_id: str) -> dict[str, Any]:
        identifier = _clean_text(period_id, "Fiscal-period identifier", maximum=160)
        try:
            row = self.connection.execute(
                "SELECT * FROM periods WHERE id = ? AND workspace_id = ?", (identifier, workspace_id)
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local fiscal-period reference.") from exc
        if row is None:
            raise PlatformError("Fiscal-period reference was not found in the selected workspace.")
        return dict(row)

    def _journal(self, workspace_id: str, organization_id: str, journal_code: str) -> dict[str, Any]:
        try:
            row = self.connection.execute(
                """
                SELECT * FROM finance_journals
                WHERE workspace_id = ? AND organization_id = ? AND journal_code = ?
                """,
                (workspace_id, organization_id, journal_code),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local finance journal.") from exc
        if row is None:
            raise PlatformError("Finance journal was not found in the selected organization.")
        return _public_record(row)

    def _entry(self, entry_id: str) -> dict[str, Any]:
        identifier = _clean_text(entry_id, "Ledger-entry identifier", maximum=160)
        try:
            row = self.connection.execute(
                """
                SELECT ledger_entries.*, organizations.organization_code, legal_entities.entity_code,
                       periods.name AS period_name, finance_journals.journal_code,
                       charts_of_accounts.chart_code
                FROM ledger_entries
                JOIN organizations ON organizations.id = ledger_entries.organization_id
                JOIN legal_entities ON legal_entities.id = ledger_entries.legal_entity_id
                JOIN periods ON periods.id = ledger_entries.period_id
                JOIN finance_journals ON finance_journals.id = ledger_entries.finance_journal_id
                JOIN charts_of_accounts ON charts_of_accounts.id = ledger_entries.chart_id
                WHERE ledger_entries.id = ?
                """,
                (identifier,),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local ledger-control entry.") from exc
        if row is None:
            raise PlatformError("Ledger-control entry was not found.")
        return dict(row)
