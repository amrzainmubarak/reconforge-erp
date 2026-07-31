"""Tenant-scoped PostgreSQL foundation for the governed Finance Core contract."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from typing import Any

from reconforge.application.finance_core import MAX_LIST_LIMIT, FinanceCoreSummary
from reconforge.domain.models import utc_now_text
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.io.persisted import PersistedJsonError, encode_postgres_outbox_payload
from reconforge.platform.common import PlatformError, platform_id
from reconforge.utils.money import InvalidAmountError, Money

_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,63}$")
ACCOUNT_TYPES = ("Asset", "Liability", "Equity", "Income", "Expense", "Off Balance")
NORMAL_BALANCES = ("Debit", "Credit")
DIMENSION_TYPES = ("Cost Center", "Department", "Project", "Custom")
JOURNAL_TYPES = ("General", "Sales", "Purchase", "Bank", "Cash", "Adjustment")
ENTRY_SOURCE_TYPES = ("Manual", "Imported", "Generated")
ENTRY_STATUSES = ("Draft", "Validated", "Voided")
MAX_ENTRY_LINES = 1_000
_ENTRY_NUMBER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._/-]{0,63}$")


class PostgresFinanceCoreError(RuntimeError):
    """Safe failure from the tenant-bound Finance Core adapter."""


def _row(value: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {column: value[column] for column in columns}
    return dict(zip(columns, value, strict=True))


def _text(value: object, label: str, *, maximum: int = 160, required: bool = True) -> str:
    raw = str(value).strip() if value is not None else ""
    if any(ord(character) < 32 or ord(character) == 127 for character in raw):
        raise PlatformError(f"{label} must contain printable characters only.")
    cleaned = " ".join(raw.split())
    if required and not cleaned:
        raise PlatformError(f"{label} is required.")
    if len(cleaned) > maximum:
        raise PlatformError(f"{label} must not exceed {maximum} characters.")
    return cleaned


def _code(value: object, label: str) -> str:
    cleaned = _text(value, label, maximum=64).upper()
    if not _CODE_PATTERN.fullmatch(cleaned):
        raise PlatformError(f"{label} must use 1-64 uppercase letters, numbers, dots, underscores, or hyphens.")
    return cleaned


def _page(limit: int, offset: int) -> tuple[int, int]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise PlatformError("Limit must be an integer between 1 and 500.")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise PlatformError("Offset must be a non-negative integer.")
    return limit, offset


def _choice(value: object, label: str, choices: tuple[str, ...]) -> str:
    candidate = _text(value, label, maximum=40).title()
    selected = {choice.lower(): choice for choice in choices}.get(candidate.lower())
    if selected is None:
        raise PlatformError(f"{label} must be one of: {', '.join(choices)}.")
    return selected


def _entry_number(value: object) -> str:
    number = _text(value, "Entry number", maximum=64).upper()
    if not _ENTRY_NUMBER_PATTERN.fullmatch(number):
        raise PlatformError("Entry number contains unsupported characters.")
    return number


def _iso_date(value: object, label: str) -> date:
    raw = _text(value, label, maximum=10)
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise PlatformError(f"{label} must use YYYY-MM-DD format.") from exc
    if parsed.isoformat() != raw:
        raise PlatformError(f"{label} must use YYYY-MM-DD format.")
    return parsed


def _amount_to_minor(value: object, currency_code: str, label: str) -> int:
    try:
        money = Money.from_exact(value, currency=currency_code, strict_precision=True)
    except InvalidAmountError as exc:
        message = str(exc)
        if "binary floating-point" in message:
            raise PlatformError(f"{label} must be supplied as an exact decimal string or integer.") from exc
        if "precision" in message:
            raise PlatformError(f"{label} exceeds the currency's decimal precision.") from exc
        raise PlatformError(f"{label} must be a valid non-negative decimal amount.") from exc
    if money.amount < 0:
        raise PlatformError(f"{label} must be a valid non-negative decimal amount.")
    minor = money.to_minor_units()
    if minor > 9_000_000_000_000_000_000:
        raise PlatformError(f"{label} exceeds the supported amount range.")
    return minor


def _minor_to_text(value: int, minor_units: int) -> str:
    amount = Decimal(value).scaleb(-minor_units)
    return f"{amount:.{minor_units}f}"


class PostgresFinanceCoreRepository:
    """Implement Finance Core use cases under one forced-RLS tenant scope."""

    _CHART_COLUMNS = (
        "id",
        "workspace_id",
        "organization_code",
        "chart_code",
        "name",
        "description",
        "active",
        "created_at",
        "updated_at",
    )
    _ACCOUNT_COLUMNS = (
        "id",
        "workspace_id",
        "chart_id",
        "parent_account_id",
        "account_code",
        "account_name",
        "account_type",
        "normal_balance",
        "allow_posting",
        "allow_manual_posting",
        "reconciliation_required",
        "active",
        "description",
        "created_at",
        "updated_at",
        "chart_code",
        "parent_account_code",
    )
    _DIMENSION_COLUMNS = (
        "id",
        "workspace_id",
        "organization_code",
        "dimension_code",
        "name",
        "dimension_type",
        "required_on_entries",
        "active",
        "created_at",
        "updated_at",
    )
    _DIMENSION_VALUE_COLUMNS = (
        "id",
        "workspace_id",
        "dimension_id",
        "value_code",
        "name",
        "active",
        "created_at",
        "updated_at",
        "dimension_code",
    )
    _JOURNAL_COLUMNS = (
        "id",
        "workspace_id",
        "chart_id",
        "organization_code",
        "journal_code",
        "name",
        "currency_code",
        "journal_type",
        "active",
        "created_at",
        "updated_at",
        "chart_code",
    )
    _ENTRY_COLUMNS = (
        "id",
        "workspace_id",
        "journal_id",
        "organization_code",
        "entity_code",
        "period_id",
        "entry_number",
        "posting_date",
        "description",
        "external_reference",
        "source_type",
        "status",
        "currency_code",
        "total_debit_minor",
        "total_credit_minor",
        "created_by",
        "validated_by",
        "voided_by",
        "validation_reason",
        "void_reason",
        "created_at",
        "updated_at",
        "validated_at",
        "voided_at",
        "journal_code",
        "chart_code",
        "period_name",
    )

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, self.tenant_id)
                yield
        except (PlatformError, PostgresFinanceCoreError):
            raise
        except Exception as exc:
            raise PostgresFinanceCoreError("PostgreSQL Finance Core operation failed.") from exc

    def _workspace_id(self, workspace: str, *, required: bool = True) -> str | None:
        row = self.connection.execute(
            "SELECT id FROM reconforge.domain_workspaces WHERE tenant_id=%s AND name=%s",
            (self.tenant_id, _text(workspace, "Workspace name")),
        ).fetchone()
        if row is None:
            if required:
                raise PostgresFinanceCoreError("Finance Core workspace was not found for this tenant.")
            return None
        return str(row["id"] if isinstance(row, Mapping) else row[0])

    def _required_workspace_id(self, workspace: str) -> str:
        workspace_id = self._workspace_id(workspace)
        if workspace_id is None:
            raise PostgresFinanceCoreError("Finance Core workspace was not found for this tenant.")
        return workspace_id

    def _event(
        self, *, actor_label: str, object_type: str, object_id: str, action: str, metadata: dict[str, Any]
    ) -> None:
        try:
            payload = encode_postgres_outbox_payload(metadata).text
        except PersistedJsonError as exc:
            raise PostgresFinanceCoreError("Finance Core event payload is invalid.") from exc
        self.connection.execute(
            """INSERT INTO reconforge.outbox_events
               (tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload)
               VALUES (%s,%s,%s,%s,%s,CAST(%s AS jsonb))
               ON CONFLICT (tenant_id,event_id) DO NOTHING""",
            (self.tenant_id, platform_id("OBX", action, object_id), action, object_type, object_id, payload),
        )
        PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=actor_label, object_type=object_type, object_id=object_id, action=action, metadata=metadata
        )

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
        code = _code(chart_code, "Chart code")
        normalized_org = _code(organization_code, "Organization code") if organization_code.strip() else ""
        with self._transaction():
            workspace_id = self._required_workspace_id(workspace)
            if (
                normalized_org
                and self.connection.execute(
                    "SELECT 1 FROM reconforge.organizations WHERE tenant_id=%s AND organization_code=%s AND active=TRUE",
                    (self.tenant_id, normalized_org),
                ).fetchone()
                is None
            ):
                raise PlatformError("Finance Core organization was not found or inactive.")
            chart_id = platform_id("COA", workspace_id, code)
            if (
                not active
                and self.connection.execute(
                    "SELECT 1 FROM reconforge.finance_accounts WHERE tenant_id=%s AND chart_id=%s AND active=TRUE LIMIT 1",
                    (self.tenant_id, chart_id),
                ).fetchone()
                is not None
            ):
                raise PlatformError("Deactivate active accounts before deactivating their chart.")
            now = utc_now_text()
            row = self.connection.execute(
                """INSERT INTO reconforge.finance_charts
                   (tenant_id,id,workspace_id,organization_code,chart_code,name,description,active,created_at,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (tenant_id,workspace_id,chart_code) DO UPDATE SET
                    organization_code=excluded.organization_code,name=excluded.name,
                    description=excluded.description,active=excluded.active,updated_at=excluded.updated_at
                   RETURNING id,workspace_id,organization_code,chart_code,name,description,active,created_at,updated_at""",
                (
                    self.tenant_id,
                    chart_id,
                    workspace_id,
                    normalized_org,
                    code,
                    _text(name, "Chart name"),
                    _text(description, "Chart description", maximum=500, required=False),
                    active,
                    now,
                    now,
                ),
            ).fetchone()
            if row is None:
                raise PostgresFinanceCoreError("Chart of accounts was not found after persistence.")
            record = _row(row, self._CHART_COLUMNS)
            self._event(
                actor_label=actor_label,
                object_type="chart_of_accounts",
                object_id=chart_id,
                action="chart_of_accounts_upserted",
                metadata={"chart_code": code, "organization_code": normalized_org, "active": active},
            )
            return record

    def list_charts(
        self, *, workspace: str = "default", limit: int = 500, offset: int = 0, actor_label: str = "local-cli"
    ) -> list[dict[str, Any]]:
        del actor_label
        page_limit, page_offset = _page(limit, offset)
        with self._transaction():
            workspace_id = self._workspace_id(workspace, required=False)
            if workspace_id is None:
                return []
            rows = self.connection.execute(
                """SELECT id,workspace_id,organization_code,chart_code,name,description,active,created_at,updated_at
                   FROM reconforge.finance_charts WHERE tenant_id=%s AND workspace_id=%s
                   ORDER BY chart_code LIMIT %s OFFSET %s""",
                (self.tenant_id, workspace_id, page_limit, page_offset),
            ).fetchall()
            return [_row(row, self._CHART_COLUMNS) for row in rows]

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
        code = _code(account_code, "Account code")
        selected_type = _choice(account_type, "Account type", ACCOUNT_TYPES)
        selected_balance = _choice(normal_balance, "Normal balance", NORMAL_BALANCES)
        chart_code_value = _code(chart_code, "Chart code")
        parent_code = _code(parent_account_code, "Parent account code") if parent_account_code.strip() else ""
        with self._transaction():
            workspace_id = self._required_workspace_id(workspace)
            chart = self.connection.execute(
                "SELECT id,active FROM reconforge.finance_charts WHERE tenant_id=%s AND workspace_id=%s AND chart_code=%s",
                (self.tenant_id, workspace_id, chart_code_value),
            ).fetchone()
            if chart is None or not bool(chart["active"] if isinstance(chart, Mapping) else chart[1]):
                raise PlatformError("Accounts require an active chart of accounts.")
            chart_id = str(chart["id"] if isinstance(chart, Mapping) else chart[0])
            account_id = platform_id("ACC", workspace_id, code)
            existing = self.connection.execute(
                "SELECT id,chart_id FROM reconforge.finance_accounts WHERE tenant_id=%s AND workspace_id=%s AND account_code=%s",
                (self.tenant_id, workspace_id, code),
            ).fetchone()
            if existing is not None:
                account_id = str(existing["id"] if isinstance(existing, Mapping) else existing[0])
                existing_chart = str(existing["chart_id"] if isinstance(existing, Mapping) else existing[1])
                if existing_chart != chart_id:
                    raise PlatformError("An account code cannot be moved between charts in this foundation.")
            parent_id: str | None = None
            if parent_code:
                parent = self.connection.execute(
                    "SELECT id FROM reconforge.finance_accounts WHERE tenant_id=%s AND chart_id=%s AND account_code=%s",
                    (self.tenant_id, chart_id, parent_code),
                ).fetchone()
                if parent is None:
                    raise PlatformError("Parent financial account was not found.")
                parent_id = str(parent["id"] if isinstance(parent, Mapping) else parent[0])
                if parent_id == account_id:
                    raise PlatformError("An account cannot be its own parent.")
                cycle = self.connection.execute(
                    """WITH RECURSIVE descendants(id) AS (
                         SELECT id FROM reconforge.finance_accounts WHERE tenant_id=%s AND parent_account_id=%s
                         UNION ALL SELECT child.id FROM reconforge.finance_accounts child
                         JOIN descendants parent ON child.parent_account_id=parent.id
                         WHERE child.tenant_id=%s)
                       SELECT 1 FROM descendants WHERE id=%s LIMIT 1""",
                    (self.tenant_id, account_id, self.tenant_id, parent_id),
                ).fetchone()
                if cycle is not None:
                    raise PlatformError("Account hierarchy must remain acyclic.")
            if (
                not active
                and self.connection.execute(
                    "SELECT 1 FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND account_id=%s LIMIT 1",
                    (self.tenant_id, account_id),
                ).fetchone()
                is not None
            ):
                raise PlatformError("Accounts referenced by ledger-control lines cannot be deactivated.")
            now = utc_now_text()
            self.connection.execute(
                """INSERT INTO reconforge.finance_accounts
                   (tenant_id,id,workspace_id,chart_id,parent_account_id,account_code,name,account_type,
                    normal_balance,allow_posting,allow_manual_posting,reconciliation_required,active,
                    description,created_at,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (tenant_id,chart_id,account_code) DO UPDATE SET
                    parent_account_id=excluded.parent_account_id,name=excluded.name,
                    account_type=excluded.account_type,normal_balance=excluded.normal_balance,
                    allow_posting=excluded.allow_posting,allow_manual_posting=excluded.allow_manual_posting,
                    reconciliation_required=excluded.reconciliation_required,active=excluded.active,
                    description=excluded.description,updated_at=excluded.updated_at""",
                (
                    self.tenant_id,
                    account_id,
                    workspace_id,
                    chart_id,
                    parent_id,
                    code,
                    _text(name, "Account name"),
                    selected_type,
                    selected_balance,
                    allow_posting,
                    allow_manual_posting,
                    reconciliation_required,
                    active,
                    _text(description, "Account description", maximum=500, required=False),
                    now,
                    now,
                ),
            )
            record = self._account_record(account_id)
            self._event(
                actor_label=actor_label,
                object_type="financial_account",
                object_id=account_id,
                action="financial_account_upserted",
                metadata={"account_code": code, "chart_code": chart_code_value, "active": active},
            )
            return record

    def _account_record(self, account_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            """SELECT accounts.id,accounts.workspace_id,accounts.chart_id,accounts.parent_account_id,
                      accounts.account_code,accounts.name AS account_name,accounts.account_type,
                      accounts.normal_balance,accounts.allow_posting,accounts.allow_manual_posting,
                      accounts.reconciliation_required,accounts.active,accounts.description,
                      accounts.created_at,accounts.updated_at,charts.chart_code,
                      parent.account_code AS parent_account_code
               FROM reconforge.finance_accounts accounts
               JOIN reconforge.finance_charts charts ON charts.tenant_id=accounts.tenant_id AND charts.id=accounts.chart_id
               LEFT JOIN reconforge.finance_accounts parent ON parent.tenant_id=accounts.tenant_id AND parent.id=accounts.parent_account_id
               WHERE accounts.tenant_id=%s AND accounts.id=%s""",
            (self.tenant_id, account_id),
        ).fetchone()
        if row is None:
            raise PostgresFinanceCoreError("Finance Core account was not found after persistence.")
        return _row(row, self._ACCOUNT_COLUMNS)

    def list_accounts(
        self,
        *,
        workspace: str = "default",
        chart_code: str = "",
        active_only: bool = False,
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        del actor_label
        page_limit, page_offset = _page(limit, offset)
        normalized_chart = _code(chart_code, "Chart code") if chart_code else ""
        with self._transaction():
            workspace_id = self._workspace_id(workspace, required=False)
            if workspace_id is None:
                return []
            query = """SELECT accounts.id,accounts.workspace_id,accounts.chart_id,accounts.parent_account_id,
                              accounts.account_code,accounts.name AS account_name,accounts.account_type,
                              accounts.normal_balance,accounts.allow_posting,accounts.allow_manual_posting,
                              accounts.reconciliation_required,accounts.active,accounts.description,
                              accounts.created_at,accounts.updated_at,charts.chart_code,
                              parent.account_code AS parent_account_code
                       FROM reconforge.finance_accounts accounts
                       JOIN reconforge.finance_charts charts ON charts.tenant_id=accounts.tenant_id AND charts.id=accounts.chart_id
                       LEFT JOIN reconforge.finance_accounts parent ON parent.tenant_id=accounts.tenant_id AND parent.id=accounts.parent_account_id
                       WHERE accounts.tenant_id=%s AND accounts.workspace_id=%s"""
            parameters: list[object] = [self.tenant_id, workspace_id]
            if normalized_chart:
                query += " AND charts.chart_code=%s"
                parameters.append(normalized_chart)
            if active_only:
                query += " AND accounts.active=TRUE"
            query += " ORDER BY charts.chart_code,accounts.account_code LIMIT %s OFFSET %s"
            parameters.extend((page_limit, page_offset))
            return [
                _row(row, self._ACCOUNT_COLUMNS) for row in self.connection.execute(query, tuple(parameters)).fetchall()
            ]

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
        code = _code(dimension_code, "Dimension code")
        org_code = _code(organization_code, "Organization code") if organization_code.strip() else ""
        selected_type = _choice(dimension_type, "Dimension type", DIMENSION_TYPES)
        with self._transaction():
            workspace_id = self._required_workspace_id(workspace)
            if (
                org_code
                and self.connection.execute(
                    "SELECT 1 FROM reconforge.organizations WHERE tenant_id=%s AND organization_code=%s",
                    (self.tenant_id, org_code),
                ).fetchone()
                is None
            ):
                raise PlatformError("Finance Core organization was not found.")
            dimension_id = platform_id("DIM", workspace_id, code)
            if (
                not active
                and self.connection.execute(
                    "SELECT 1 FROM reconforge.finance_entry_line_dimensions WHERE tenant_id=%s AND dimension_id=%s LIMIT 1",
                    (self.tenant_id, dimension_id),
                ).fetchone()
                is not None
            ):
                raise PlatformError("Dimensions referenced by ledger-control lines cannot be deactivated.")
            now = utc_now_text()
            row = self.connection.execute(
                """INSERT INTO reconforge.finance_dimensions
                   (tenant_id,id,workspace_id,organization_code,dimension_code,name,dimension_type,
                    required_on_entries,active,created_at,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (tenant_id,workspace_id,dimension_code) DO UPDATE SET
                    organization_code=excluded.organization_code,name=excluded.name,
                    dimension_type=excluded.dimension_type,required_on_entries=excluded.required_on_entries,
                    active=excluded.active,updated_at=excluded.updated_at
                   RETURNING id,workspace_id,organization_code,dimension_code,name,dimension_type,
                             required_on_entries,active,created_at,updated_at""",
                (
                    self.tenant_id,
                    dimension_id,
                    workspace_id,
                    org_code,
                    code,
                    _text(name, "Dimension name"),
                    selected_type,
                    required_on_entries,
                    active,
                    now,
                    now,
                ),
            ).fetchone()
            if row is None:
                raise PostgresFinanceCoreError("Accounting dimension was not found after persistence.")
            record = _row(row, self._DIMENSION_COLUMNS)
            self._event(
                actor_label=actor_label,
                object_type="accounting_dimension",
                object_id=dimension_id,
                action="accounting_dimension_upserted",
                metadata={"dimension_code": code, "required_on_entries": required_on_entries, "active": active},
            )
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
        dimension_code_value = _code(dimension_code, "Dimension code")
        code = _code(value_code, "Dimension value code")
        with self._transaction():
            workspace_id = self._required_workspace_id(workspace)
            dimension = self.connection.execute(
                "SELECT id,active FROM reconforge.finance_dimensions WHERE tenant_id=%s AND workspace_id=%s AND dimension_code=%s",
                (self.tenant_id, workspace_id, dimension_code_value),
            ).fetchone()
            if dimension is None or not bool(dimension["active"] if isinstance(dimension, Mapping) else dimension[1]):
                raise PlatformError("Dimension values require an active dimension.")
            dimension_id = str(dimension["id"] if isinstance(dimension, Mapping) else dimension[0])
            value_id = platform_id("DIMV", dimension_id, code)
            if (
                not active
                and self.connection.execute(
                    "SELECT 1 FROM reconforge.finance_entry_line_dimensions WHERE tenant_id=%s AND dimension_value_id=%s LIMIT 1",
                    (self.tenant_id, value_id),
                ).fetchone()
                is not None
            ):
                raise PlatformError("Dimension values referenced by ledger-control lines cannot be deactivated.")
            now = utc_now_text()
            row = self.connection.execute(
                """INSERT INTO reconforge.finance_dimension_values
                   (tenant_id,id,workspace_id,dimension_id,value_code,name,active,created_at,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (tenant_id,dimension_id,value_code) DO UPDATE SET
                    name=excluded.name,active=excluded.active,updated_at=excluded.updated_at
                   RETURNING id,workspace_id,dimension_id,value_code,name,active,created_at,updated_at""",
                (
                    self.tenant_id,
                    value_id,
                    workspace_id,
                    dimension_id,
                    code,
                    _text(name, "Dimension value name"),
                    active,
                    now,
                    now,
                ),
            ).fetchone()
            if row is None:
                raise PostgresFinanceCoreError("Accounting dimension value was not found after persistence.")
            record = _row(row, self._DIMENSION_VALUE_COLUMNS[:-1])
            record["dimension_code"] = dimension_code_value
            self._event(
                actor_label=actor_label,
                object_type="accounting_dimension_value",
                object_id=value_id,
                action="accounting_dimension_value_upserted",
                metadata={"dimension_code": dimension_code_value, "value_code": code, "active": active},
            )
            return record

    def list_dimensions(
        self, *, workspace: str = "default", limit: int = 500, offset: int = 0, actor_label: str = "local-cli"
    ) -> list[dict[str, Any]]:
        del actor_label
        page_limit, page_offset = _page(limit, offset)
        with self._transaction():
            workspace_id = self._workspace_id(workspace, required=False)
            if workspace_id is None:
                return []
            rows = self.connection.execute(
                """SELECT id,workspace_id,organization_code,dimension_code,name,dimension_type,
                          required_on_entries,active,created_at,updated_at
                   FROM reconforge.finance_dimensions WHERE tenant_id=%s AND workspace_id=%s
                   ORDER BY dimension_code LIMIT %s OFFSET %s""",
                (self.tenant_id, workspace_id, page_limit, page_offset),
            ).fetchall()
            return [_row(row, self._DIMENSION_COLUMNS) for row in rows]

    def list_dimension_values(
        self,
        *,
        dimension_code: str = "",
        workspace: str = "default",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        del actor_label
        page_limit, page_offset = _page(limit, offset)
        normalized = _code(dimension_code, "Dimension code") if dimension_code else ""
        with self._transaction():
            workspace_id = self._workspace_id(workspace, required=False)
            if workspace_id is None:
                return []
            query = """SELECT values_.id,values_.workspace_id,values_.dimension_id,values_.value_code,
                              values_.name,values_.active,values_.created_at,values_.updated_at,
                              dimensions.dimension_code
                       FROM reconforge.finance_dimension_values values_
                       JOIN reconforge.finance_dimensions dimensions
                        ON dimensions.tenant_id=values_.tenant_id AND dimensions.id=values_.dimension_id
                       WHERE values_.tenant_id=%s AND values_.workspace_id=%s"""
            parameters: list[object] = [self.tenant_id, workspace_id]
            if normalized:
                query += " AND dimensions.dimension_code=%s"
                parameters.append(normalized)
            query += " ORDER BY dimensions.dimension_code,values_.value_code LIMIT %s OFFSET %s"
            parameters.extend((page_limit, page_offset))
            return [
                _row(row, self._DIMENSION_VALUE_COLUMNS)
                for row in self.connection.execute(query, tuple(parameters)).fetchall()
            ]

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
        code = _code(journal_code, "Journal code")
        org_code = _code(organization_code, "Organization code")
        currency = _code(currency_code, "Currency code")
        chart_code_value = _code(chart_code, "Chart code")
        selected_type = _choice(journal_type, "Journal type", JOURNAL_TYPES)
        with self._transaction():
            workspace_id = self._required_workspace_id(workspace)
            organization = self.connection.execute(
                "SELECT active FROM reconforge.organizations WHERE tenant_id=%s AND organization_code=%s",
                (self.tenant_id, org_code),
            ).fetchone()
            if organization is None or not bool(
                organization["active"] if isinstance(organization, Mapping) else organization[0]
            ):
                raise PlatformError("Finance journals require an active organization.")
            chart = self.connection.execute(
                "SELECT id,organization_code,active FROM reconforge.finance_charts WHERE tenant_id=%s AND workspace_id=%s AND chart_code=%s",
                (self.tenant_id, workspace_id, chart_code_value),
            ).fetchone()
            if chart is None or not bool(chart["active"] if isinstance(chart, Mapping) else chart[2]):
                raise PlatformError("Finance journals require an active chart of accounts.")
            chart_id = str(chart["id"] if isinstance(chart, Mapping) else chart[0])
            chart_org = str(chart["organization_code"] if isinstance(chart, Mapping) else chart[1])
            if chart_org and chart_org != org_code:
                raise PlatformError("Finance journal organization must match its chart of accounts.")
            currency_row = self.connection.execute(
                "SELECT active FROM reconforge.currencies WHERE tenant_id=%s AND code=%s",
                (self.tenant_id, currency),
            ).fetchone()
            if currency_row is None or not bool(
                currency_row["active"] if isinstance(currency_row, Mapping) else currency_row[0]
            ):
                raise PlatformError("Finance journals require an active currency reference.")
            journal_id = platform_id("FJ", workspace_id, org_code, code)
            existing = self.connection.execute(
                "SELECT id,chart_id,currency_code FROM reconforge.finance_journals WHERE tenant_id=%s AND workspace_id=%s AND organization_code=%s AND journal_code=%s",
                (self.tenant_id, workspace_id, org_code, code),
            ).fetchone()
            if existing is not None:
                journal_id = str(existing["id"] if isinstance(existing, Mapping) else existing[0])
                old_chart = str(existing["chart_id"] if isinstance(existing, Mapping) else existing[1])
                old_currency = str(existing["currency_code"] if isinstance(existing, Mapping) else existing[2])
                if (old_chart != chart_id or old_currency != currency) and self.connection.execute(
                    "SELECT 1 FROM reconforge.finance_entries WHERE tenant_id=%s AND journal_id=%s LIMIT 1",
                    (self.tenant_id, journal_id),
                ).fetchone() is not None:
                    raise PlatformError("A referenced finance journal cannot change its chart or currency.")
            if (
                not active
                and self.connection.execute(
                    "SELECT 1 FROM reconforge.finance_entries WHERE tenant_id=%s AND journal_id=%s LIMIT 1",
                    (self.tenant_id, journal_id),
                ).fetchone()
                is not None
            ):
                raise PlatformError("Journals referenced by ledger-control entries cannot be deactivated.")
            now = utc_now_text()
            self.connection.execute(
                """INSERT INTO reconforge.finance_journals
                   (tenant_id,id,workspace_id,chart_id,organization_code,journal_code,name,
                    currency_code,journal_type,active,created_at,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (tenant_id,workspace_id,organization_code,journal_code) DO UPDATE SET
                    chart_id=excluded.chart_id,name=excluded.name,currency_code=excluded.currency_code,
                    journal_type=excluded.journal_type,active=excluded.active,updated_at=excluded.updated_at""",
                (
                    self.tenant_id,
                    journal_id,
                    workspace_id,
                    chart_id,
                    org_code,
                    code,
                    _text(name, "Journal name"),
                    currency,
                    selected_type,
                    active,
                    now,
                    now,
                ),
            )
            record = self._journal_record(journal_id)
            self._event(
                actor_label=actor_label,
                object_type="finance_journal",
                object_id=journal_id,
                action="finance_journal_upserted",
                metadata={"journal_code": code, "organization_code": org_code, "active": active},
            )
            return record

    def _journal_record(self, journal_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            """SELECT journals.id,journals.workspace_id,journals.chart_id,journals.organization_code,
                      journals.journal_code,journals.name,journals.currency_code,journals.journal_type,
                      journals.active,journals.created_at,journals.updated_at,charts.chart_code
               FROM reconforge.finance_journals journals JOIN reconforge.finance_charts charts
                ON charts.tenant_id=journals.tenant_id AND charts.id=journals.chart_id
               WHERE journals.tenant_id=%s AND journals.id=%s""",
            (self.tenant_id, journal_id),
        ).fetchone()
        if row is None:
            raise PostgresFinanceCoreError("Finance journal was not found after persistence.")
        return _row(row, self._JOURNAL_COLUMNS)

    def list_journals(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        del actor_label
        page_limit, page_offset = _page(limit, offset)
        normalized_org = _code(organization_code, "Organization code") if organization_code else ""
        with self._transaction():
            workspace_id = self._workspace_id(workspace, required=False)
            if workspace_id is None:
                return []
            query = """SELECT journals.id,journals.workspace_id,journals.chart_id,journals.organization_code,
                              journals.journal_code,journals.name,journals.currency_code,journals.journal_type,
                              journals.active,journals.created_at,journals.updated_at,charts.chart_code
                       FROM reconforge.finance_journals journals JOIN reconforge.finance_charts charts
                        ON charts.tenant_id=journals.tenant_id AND charts.id=journals.chart_id
                       WHERE journals.tenant_id=%s AND journals.workspace_id=%s"""
            parameters: list[object] = [self.tenant_id, workspace_id]
            if normalized_org:
                query += " AND journals.organization_code=%s"
                parameters.append(normalized_org)
            query += " ORDER BY journals.organization_code,journals.journal_code LIMIT %s OFFSET %s"
            parameters.extend((page_limit, page_offset))
            return [
                _row(row, self._JOURNAL_COLUMNS) for row in self.connection.execute(query, tuple(parameters)).fetchall()
            ]

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
        number = _entry_number(entry_number)
        org_code = _code(organization_code, "Organization code")
        entity_code_value = _code(entity_code, "Entity code")
        journal_code_value = _code(journal_code, "Journal code")
        period_identifier = _text(period_id, "Fiscal-period identifier")
        posted_on = _iso_date(posting_date, "Posting date")
        selected_source = _choice(source_type, "Entry source type", ENTRY_SOURCE_TYPES)
        if not 2 <= len(lines) <= MAX_ENTRY_LINES:
            raise PlatformError(f"Ledger-control entries require between 2 and {MAX_ENTRY_LINES} lines.")
        with self._transaction():
            workspace_id = self._required_workspace_id(workspace)
            organization = self.connection.execute(
                "SELECT id,active FROM reconforge.organizations WHERE tenant_id=%s AND organization_code=%s",
                (self.tenant_id, org_code),
            ).fetchone()
            if organization is None or not bool(
                organization["active"] if isinstance(organization, Mapping) else organization[1]
            ):
                raise PlatformError("Ledger-control entries require an active organization.")
            organization_id = str(organization["id"] if isinstance(organization, Mapping) else organization[0])
            entity = self.connection.execute(
                "SELECT id,currency_code,active FROM reconforge.legal_entities WHERE tenant_id=%s AND organization_id=%s AND entity_code=%s",
                (self.tenant_id, organization_id, entity_code_value),
            ).fetchone()
            if entity is None or not bool(entity["active"] if isinstance(entity, Mapping) else entity[2]):
                raise PlatformError("Ledger-control entries require an active legal entity.")
            entity_currency = str(entity["currency_code"] if isinstance(entity, Mapping) else entity[1])
            period = self.connection.execute(
                "SELECT id,name,start_date,end_date,status FROM reconforge.fiscal_periods WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, period_identifier),
            ).fetchone()
            if period is None:
                raise PlatformError("Fiscal-period reference was not found.")
            period_data = _row(period, ("id", "name", "start_date", "end_date", "status"))
            if str(period_data["status"]) != "Open":
                raise PlatformError("Ledger-control entries can be created only in an Open fiscal period.")
            if (
                not _iso_date(period_data["start_date"], "Stored period start date")
                <= posted_on
                <= _iso_date(period_data["end_date"], "Stored period end date")
            ):
                raise PlatformError("Posting date must fall inside the selected fiscal period.")
            journal = self.connection.execute(
                """SELECT id,chart_id,currency_code,active FROM reconforge.finance_journals
                   WHERE tenant_id=%s AND workspace_id=%s AND organization_code=%s AND journal_code=%s""",
                (self.tenant_id, workspace_id, org_code, journal_code_value),
            ).fetchone()
            if journal is None or not bool(journal["active"] if isinstance(journal, Mapping) else journal[3]):
                raise PlatformError("Ledger-control entries require an active finance journal.")
            journal_data = _row(journal, ("id", "chart_id", "currency_code", "active"))
            currency_code = str(journal_data["currency_code"])
            if entity_currency != currency_code:
                raise PlatformError("Journal and legal-entity currencies must match in this finance-core version.")
            currency = self.connection.execute(
                "SELECT minor_units,active FROM reconforge.currencies WHERE tenant_id=%s AND code=%s",
                (self.tenant_id, currency_code),
            ).fetchone()
            if currency is None or not bool(currency["active"] if isinstance(currency, Mapping) else currency[1]):
                raise PlatformError("Ledger-control entries require an active currency reference.")
            required_rows = self.connection.execute(
                """SELECT id,dimension_code FROM reconforge.finance_dimensions
                   WHERE tenant_id=%s AND workspace_id=%s AND active=TRUE AND required_on_entries=TRUE
                     AND (organization_code='' OR organization_code=%s)""",
                (self.tenant_id, workspace_id, org_code),
            ).fetchall()
            required_dimensions = {
                str(row["id"] if isinstance(row, Mapping) else row[0]): str(
                    row["dimension_code"] if isinstance(row, Mapping) else row[1]
                )
                for row in required_rows
            }
            prepared_lines: list[dict[str, Any]] = []
            total_debit = total_credit = 0
            for line_number, line in enumerate(lines, start=1):
                if not isinstance(line, Mapping):
                    raise PlatformError("Each ledger line must be an object.")
                account_code = _code(line.get("account_code"), "Account code")
                account = self.connection.execute(
                    """SELECT id,active,allow_posting,allow_manual_posting FROM reconforge.finance_accounts
                       WHERE tenant_id=%s AND chart_id=%s AND account_code=%s""",
                    (self.tenant_id, journal_data["chart_id"], account_code),
                ).fetchone()
                if account is None:
                    raise PlatformError("Financial account was not found in the selected chart.")
                account_data = _row(account, ("id", "active", "allow_posting", "allow_manual_posting"))
                if not bool(account_data["active"]) or not bool(account_data["allow_posting"]):
                    raise PlatformError("Ledger lines require an active posting-enabled account.")
                if selected_source == "Manual" and not bool(account_data["allow_manual_posting"]):
                    raise PlatformError("Manual entries cannot use an account that blocks manual posting.")
                debit_minor = _amount_to_minor(line.get("debit", "0"), currency_code, "Line debit")
                credit_minor = _amount_to_minor(line.get("credit", "0"), currency_code, "Line credit")
                if (debit_minor > 0) == (credit_minor > 0):
                    raise PlatformError("Each ledger line must contain exactly one non-zero debit or credit amount.")
                dimensions = self._prepare_dimensions(
                    line.get("dimensions", {}), workspace_id=workspace_id, organization_code=org_code
                )
                missing = set(required_dimensions) - set(dimensions)
                if missing:
                    codes = ", ".join(sorted(required_dimensions[item] for item in missing))
                    raise PlatformError(f"Ledger line is missing required dimensions: {codes}.")
                prepared_lines.append(
                    {
                        "line_number": line_number,
                        "account_id": account_data["id"],
                        "description": _text(
                            line.get("description", ""), "Line description", maximum=500, required=False
                        ),
                        "debit_minor": debit_minor,
                        "credit_minor": credit_minor,
                        "dimensions": dimensions,
                    }
                )
                total_debit += debit_minor
                total_credit += credit_minor
            if total_debit <= 0 or total_debit != total_credit:
                raise PlatformError("Ledger-control entry debits and credits must balance to a non-zero amount.")
            entry_id = platform_id("GLE", workspace_id, number)
            existing = self.connection.execute(
                "SELECT id,status,created_by,created_at FROM reconforge.finance_entries WHERE tenant_id=%s AND workspace_id=%s AND entry_number=%s",
                (self.tenant_id, workspace_id, number),
            ).fetchone()
            if (
                existing is not None
                and str(existing["status"] if isinstance(existing, Mapping) else existing[1]) != "Draft"
            ):
                raise PlatformError("Only Draft ledger-control entries can be replaced.")
            if existing is not None:
                entry_id = str(existing["id"] if isinstance(existing, Mapping) else existing[0])
            now = utc_now_text()
            created_by = (
                str(existing["created_by"] if isinstance(existing, Mapping) else existing[2])
                if existing
                else _text(actor_label or "local-cli", "Actor label")
            )
            created_at = (
                str(existing["created_at"] if isinstance(existing, Mapping) else existing[3]) if existing else now
            )
            if existing is not None:
                self.connection.execute(
                    "DELETE FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND entry_id=%s",
                    (self.tenant_id, entry_id),
                )
            self.connection.execute(
                """INSERT INTO reconforge.finance_entries
                   (tenant_id,id,workspace_id,journal_id,organization_code,entity_code,period_id,entry_number,
                    posting_date,description,external_reference,source_type,status,currency_code,total_debit_minor,
                    total_credit_minor,created_by,created_at,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Draft',%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (tenant_id,workspace_id,entry_number) DO UPDATE SET
                    journal_id=excluded.journal_id,organization_code=excluded.organization_code,
                    entity_code=excluded.entity_code,period_id=excluded.period_id,posting_date=excluded.posting_date,
                    description=excluded.description,external_reference=excluded.external_reference,
                    source_type=excluded.source_type,total_debit_minor=excluded.total_debit_minor,
                    total_credit_minor=excluded.total_credit_minor,updated_at=excluded.updated_at""",
                (
                    self.tenant_id,
                    entry_id,
                    workspace_id,
                    journal_data["id"],
                    org_code,
                    entity_code_value,
                    period_identifier,
                    number,
                    posted_on.isoformat(),
                    _text(description, "Entry description", maximum=500),
                    _text(external_reference, "External reference", required=False),
                    selected_source,
                    currency_code,
                    total_debit,
                    total_credit,
                    created_by,
                    created_at,
                    now,
                ),
            )
            for prepared in prepared_lines:
                line_id = platform_id("GLL", entry_id, prepared["line_number"])
                self.connection.execute(
                    """INSERT INTO reconforge.finance_entry_lines
                       (tenant_id,id,entry_id,line_number,account_id,description,debit_minor,credit_minor,currency_code)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        self.tenant_id,
                        line_id,
                        entry_id,
                        prepared["line_number"],
                        prepared["account_id"],
                        prepared["description"],
                        prepared["debit_minor"],
                        prepared["credit_minor"],
                        currency_code,
                    ),
                )
                for dimension_id, value_id in prepared["dimensions"].items():
                    self.connection.execute(
                        """INSERT INTO reconforge.finance_entry_line_dimensions
                           (tenant_id,entry_line_id,dimension_id,dimension_value_id) VALUES (%s,%s,%s,%s)""",
                        (self.tenant_id, line_id, dimension_id, value_id),
                    )
            self._validate_entry_integrity(entry_id)
            self._event(
                actor_label=actor_label,
                object_type="ledger_entry",
                object_id=entry_id,
                action="ledger_entry_draft_saved",
                metadata={
                    "entry_number": number,
                    "line_count": len(prepared_lines),
                    "currency_code": currency_code,
                    "total_minor": total_debit,
                },
            )
            return self._get_entry_in_transaction(entry_id)

    def validate_entry(self, entry_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        identifier = _text(entry_id, "Ledger-entry identifier")
        validation_reason = _text(reason, "Validation reason", maximum=500)
        validator = _text(actor_label or "local-cli", "Actor label")
        with self._transaction():
            entry = self._entry_row(identifier, lock=True)
            if entry["status"] != "Draft":
                raise PlatformError("Only Draft ledger-control entries can be validated.")
            if str(entry["created_by"]) == validator:
                raise PlatformError("Segregation of duties prevents validating your own ledger-control entry.")
            self._validate_entry_integrity(identifier)
            now = utc_now_text()
            cursor = self.connection.execute(
                """UPDATE reconforge.finance_entries SET status='Validated',validated_by=%s,validated_at=%s,
                   validation_reason=%s,updated_at=%s WHERE tenant_id=%s AND id=%s AND status='Draft'""",
                (validator, now, validation_reason, now, self.tenant_id, identifier),
            )
            if cursor.rowcount != 1:
                raise PlatformError("Ledger-control entry changed concurrently; reload and retry.")
            self._event(
                actor_label=actor_label,
                object_type="ledger_entry",
                object_id=identifier,
                action="ledger_entry_validated",
                metadata={"entry_number": entry["entry_number"], "reason": validation_reason},
            )
            return self._get_entry_in_transaction(identifier)

    def void_entry(self, entry_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        identifier = _text(entry_id, "Ledger-entry identifier")
        void_reason = _text(reason, "Void reason", maximum=500)
        actor = _text(actor_label or "local-cli", "Actor label")
        with self._transaction():
            entry = self._entry_row(identifier, lock=True)
            if entry["status"] != "Validated":
                raise PlatformError("Only Validated ledger-control entries can be voided.")
            now = utc_now_text()
            cursor = self.connection.execute(
                """UPDATE reconforge.finance_entries SET status='Voided',voided_by=%s,voided_at=%s,
                   void_reason=%s,updated_at=%s WHERE tenant_id=%s AND id=%s AND status='Validated'""",
                (actor, now, void_reason, now, self.tenant_id, identifier),
            )
            if cursor.rowcount != 1:
                raise PlatformError("Ledger-control entry changed concurrently; reload and retry.")
            self._event(
                actor_label=actor_label,
                object_type="ledger_entry",
                object_id=identifier,
                action="ledger_entry_voided",
                metadata={"entry_number": entry["entry_number"], "reason": void_reason},
            )
            return self._get_entry_in_transaction(identifier)

    def get_entry(self, entry_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        del actor_label
        with self._transaction():
            return self._get_entry_in_transaction(_text(entry_id, "Ledger-entry identifier"))

    def list_entries(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        entity_code: str = "",
        period_id: str = "",
        status: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        del actor_label
        page_limit, page_offset = _page(limit, offset)
        with self._transaction():
            workspace_id = self._workspace_id(workspace, required=False)
            if workspace_id is None:
                return []
            query = """SELECT entries.id,entries.workspace_id,entries.journal_id,entries.organization_code,
                entries.entity_code,entries.period_id,entries.entry_number,entries.posting_date,entries.description,
                entries.external_reference,entries.source_type,entries.status,entries.currency_code,
                entries.total_debit_minor,entries.total_credit_minor,entries.created_by,entries.validated_by,
                entries.voided_by,entries.validation_reason,entries.void_reason,entries.created_at,entries.updated_at,
                entries.validated_at,entries.voided_at,journals.journal_code,charts.chart_code,periods.name AS period_name
                FROM reconforge.finance_entries entries JOIN reconforge.finance_journals journals
                 ON journals.tenant_id=entries.tenant_id AND journals.id=entries.journal_id
                JOIN reconforge.finance_charts charts ON charts.tenant_id=journals.tenant_id AND charts.id=journals.chart_id
                JOIN reconforge.fiscal_periods periods ON periods.tenant_id=entries.tenant_id AND periods.id=entries.period_id
                WHERE entries.tenant_id=%s AND entries.workspace_id=%s"""
            parameters: list[object] = [self.tenant_id, workspace_id]
            for value, column, label in (
                (organization_code, "organization_code", "Organization code"),
                (entity_code, "entity_code", "Entity code"),
            ):
                if value:
                    query += f" AND entries.{column}=%s"
                    parameters.append(_code(value, label))
            if period_id:
                query += " AND entries.period_id=%s"
                parameters.append(_text(period_id, "Fiscal-period identifier"))
            if status:
                query += " AND entries.status=%s"
                parameters.append(_choice(status, "Entry status", ENTRY_STATUSES))
            query += " ORDER BY entries.posting_date DESC,entries.entry_number LIMIT %s OFFSET %s"
            parameters.extend((page_limit, page_offset))
            return [
                _row(row, self._ENTRY_COLUMNS) for row in self.connection.execute(query, tuple(parameters)).fetchall()
            ]

    def trial_balance(
        self,
        *,
        period_id: str,
        organization_code: str,
        entity_code: str,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, object]:
        del actor_label
        org_code = _code(organization_code, "Organization code")
        entity_code_value = _code(entity_code, "Entity code")
        period_identifier = _text(period_id, "Fiscal-period identifier")
        with self._transaction():
            workspace_id = self._required_workspace_id(workspace)
            period = self.connection.execute(
                "SELECT name FROM reconforge.fiscal_periods WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, period_identifier),
            ).fetchone()
            if period is None:
                raise PlatformError("Fiscal-period reference was not found.")
            organization = self.connection.execute(
                "SELECT id FROM reconforge.organizations WHERE tenant_id=%s AND organization_code=%s",
                (self.tenant_id, org_code),
            ).fetchone()
            if organization is None:
                raise PlatformError("Organization reference was not found.")
            organization_id = str(organization["id"] if isinstance(organization, Mapping) else organization[0])
            entity = self.connection.execute(
                "SELECT currency_code FROM reconforge.legal_entities WHERE tenant_id=%s AND organization_id=%s AND entity_code=%s",
                (self.tenant_id, organization_id, entity_code_value),
            ).fetchone()
            if entity is None:
                raise PlatformError("Legal-entity reference was not found.")
            currency_code = str(entity["currency_code"] if isinstance(entity, Mapping) else entity[0])
            currency = self.connection.execute(
                "SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s",
                (self.tenant_id, currency_code),
            ).fetchone()
            if currency is None:
                raise PlatformError("Currency reference was not found.")
            minor_units = int(currency["minor_units"] if isinstance(currency, Mapping) else currency[0])
            rows = self.connection.execute(
                """SELECT accounts.account_code,accounts.name,accounts.account_type,accounts.normal_balance,
                    SUM(lines.debit_minor),SUM(lines.credit_minor) FROM reconforge.finance_entry_lines lines
                    JOIN reconforge.finance_entries entries ON entries.tenant_id=lines.tenant_id AND entries.id=lines.entry_id
                    JOIN reconforge.finance_accounts accounts ON accounts.tenant_id=lines.tenant_id AND accounts.id=lines.account_id
                    WHERE entries.tenant_id=%s AND entries.workspace_id=%s AND entries.organization_code=%s
                      AND entries.entity_code=%s AND entries.period_id=%s AND entries.status='Validated'
                    GROUP BY accounts.id,accounts.account_code,accounts.name,accounts.account_type,accounts.normal_balance
                    ORDER BY accounts.account_code""",
                (self.tenant_id, workspace_id, org_code, entity_code_value, period_identifier),
            ).fetchall()
            records: list[dict[str, object]] = []
            total_debit = total_credit = 0
            for row in rows:
                data = _row(
                    row,
                    ("account_code", "account_name", "account_type", "normal_balance", "debit_minor", "credit_minor"),
                )
                debit_minor, credit_minor = int(data["debit_minor"] or 0), int(data["credit_minor"] or 0)
                total_debit += debit_minor
                total_credit += credit_minor
                balance_minor = debit_minor - credit_minor
                data.update(
                    {
                        "debit_minor": debit_minor,
                        "credit_minor": credit_minor,
                        "balance_minor": balance_minor,
                        "debit": _minor_to_text(debit_minor, minor_units),
                        "credit": _minor_to_text(credit_minor, minor_units),
                        "balance": _minor_to_text(balance_minor, minor_units),
                    }
                )
                records.append(data)
            return {
                "schema_version": 1,
                "source": {"kind": "postgres-ledger-control", "local_first": False, "external_calls": False},
                "workspace": _text(workspace, "Workspace name"),
                "organization_code": org_code,
                "entity_code": entity_code_value,
                "period_id": period_identifier,
                "period_name": str(period["name"] if isinstance(period, Mapping) else period[0]),
                "currency_code": currency_code,
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
        del actor_label
        workspace_name = _text(workspace, "Workspace name")
        with self._transaction():
            workspace_id = self._workspace_id(workspace_name, required=False)
            if workspace_id is None:
                return FinanceCoreSummary(workspace_name, 0, 0, 0, 0, 0, 0, 0, 0)
            row = self.connection.execute(
                """SELECT
                 (SELECT COUNT(*) FROM reconforge.finance_charts WHERE tenant_id=%s AND workspace_id=%s),
                 (SELECT COUNT(*) FROM reconforge.finance_accounts WHERE tenant_id=%s AND workspace_id=%s),
                 (SELECT COUNT(*) FROM reconforge.finance_dimensions WHERE tenant_id=%s AND workspace_id=%s),
                 (SELECT COUNT(*) FROM reconforge.finance_dimension_values WHERE tenant_id=%s AND workspace_id=%s),
                 (SELECT COUNT(*) FROM reconforge.finance_journals WHERE tenant_id=%s AND workspace_id=%s),
                 (SELECT COUNT(*) FROM reconforge.finance_entries WHERE tenant_id=%s AND workspace_id=%s AND status='Draft'),
                 (SELECT COUNT(*) FROM reconforge.finance_entries WHERE tenant_id=%s AND workspace_id=%s AND status='Validated'),
                 (SELECT COUNT(*) FROM reconforge.finance_entries WHERE tenant_id=%s AND workspace_id=%s AND status='Voided')""",
                (self.tenant_id, workspace_id) * 8,
            ).fetchone()
            if row is None:
                raise PostgresFinanceCoreError("Unable to summarize PostgreSQL Finance Core records.")
            values = list(row.values()) if isinstance(row, Mapping) else list(row)
            return FinanceCoreSummary(workspace_name, *(int(value) for value in values))

    def snapshot(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, object]:
        workspace_name = _text(workspace, "Workspace name")
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
            "source": {"kind": "postgres-finance-core", "local_first": False, "external_calls": False},
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

    def _prepare_dimensions(self, raw: object, *, workspace_id: str, organization_code: str) -> dict[str, str]:
        if raw is None:
            return {}
        if not isinstance(raw, Mapping):
            raise PlatformError("Ledger line dimensions must be an object of dimension and value codes.")
        if len(raw) > 20:
            raise PlatformError("Ledger lines support at most 20 dimension assignments.")
        prepared: dict[str, str] = {}
        for raw_dimension_code, raw_value_code in raw.items():
            dimension_code = _code(raw_dimension_code, "Dimension code")
            dimension = self.connection.execute(
                """SELECT id,organization_code,active FROM reconforge.finance_dimensions
                   WHERE tenant_id=%s AND workspace_id=%s AND dimension_code=%s""",
                (self.tenant_id, workspace_id, dimension_code),
            ).fetchone()
            if dimension is None:
                raise PlatformError("Accounting dimension was not found in the selected workspace.")
            dimension_data = _row(dimension, ("id", "organization_code", "active"))
            if not bool(dimension_data["active"]):
                raise PlatformError("Ledger lines require active accounting dimensions.")
            if dimension_data["organization_code"] and dimension_data["organization_code"] != organization_code:
                raise PlatformError("Ledger line dimension belongs to a different organization.")
            value_code = _code(raw_value_code, "Dimension value code")
            value = self.connection.execute(
                """SELECT id,active FROM reconforge.finance_dimension_values
                   WHERE tenant_id=%s AND dimension_id=%s AND value_code=%s""",
                (self.tenant_id, dimension_data["id"], value_code),
            ).fetchone()
            if value is None:
                raise PlatformError("Accounting dimension value was not found.")
            value_data = _row(value, ("id", "active"))
            if not bool(value_data["active"]):
                raise PlatformError("Ledger lines require active accounting dimension values.")
            prepared[str(dimension_data["id"])] = str(value_data["id"])
        return prepared

    def _entry_row(self, entry_id: str, *, lock: bool = False) -> dict[str, Any]:
        query = """SELECT entries.id,entries.workspace_id,entries.journal_id,entries.organization_code,
                entries.entity_code,entries.period_id,entries.entry_number,entries.posting_date,entries.description,
                entries.external_reference,entries.source_type,entries.status,entries.currency_code,
                entries.total_debit_minor,entries.total_credit_minor,entries.created_by,entries.validated_by,
                entries.voided_by,entries.validation_reason,entries.void_reason,entries.created_at,entries.updated_at,
                entries.validated_at,entries.voided_at,journals.journal_code,charts.chart_code,periods.name AS period_name
                FROM reconforge.finance_entries entries JOIN reconforge.finance_journals journals
                 ON journals.tenant_id=entries.tenant_id AND journals.id=entries.journal_id
                JOIN reconforge.finance_charts charts ON charts.tenant_id=journals.tenant_id AND charts.id=journals.chart_id
                JOIN reconforge.fiscal_periods periods ON periods.tenant_id=entries.tenant_id AND periods.id=entries.period_id
                WHERE entries.tenant_id=%s AND entries.id=%s"""
        if lock:
            query += " FOR UPDATE"  # nosec B608 -- fixed allowlisted clause, never user controlled
        row = self.connection.execute(
            query,
            (self.tenant_id, entry_id),
        ).fetchone()
        if row is None:
            raise PlatformError("Ledger-control entry was not found.")
        return _row(row, self._ENTRY_COLUMNS)

    def _get_entry_in_transaction(self, entry_id: str) -> dict[str, Any]:
        entry = self._entry_row(entry_id)
        currency = self.connection.execute(
            "SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s",
            (self.tenant_id, entry["currency_code"]),
        ).fetchone()
        if currency is None:
            raise PlatformError("Currency reference was not found.")
        minor_units = int(currency["minor_units"] if isinstance(currency, Mapping) else currency[0])
        line_rows = self.connection.execute(
            """SELECT lines.id,lines.line_number,lines.account_id,lines.description,lines.debit_minor,
                      lines.credit_minor,lines.currency_code,accounts.account_code,accounts.name AS account_name
               FROM reconforge.finance_entry_lines lines JOIN reconforge.finance_accounts accounts
                ON accounts.tenant_id=lines.tenant_id AND accounts.id=lines.account_id
               WHERE lines.tenant_id=%s AND lines.entry_id=%s ORDER BY lines.line_number""",
            (self.tenant_id, entry_id),
        ).fetchall()
        dimension_rows = self.connection.execute(
            """SELECT links.entry_line_id,dimensions.dimension_code,values_.value_code
               FROM reconforge.finance_entry_line_dimensions links JOIN reconforge.finance_dimensions dimensions
                ON dimensions.tenant_id=links.tenant_id AND dimensions.id=links.dimension_id
               JOIN reconforge.finance_dimension_values values_ ON values_.tenant_id=links.tenant_id
                AND values_.id=links.dimension_value_id
               JOIN reconforge.finance_entry_lines lines ON lines.tenant_id=links.tenant_id
                AND lines.id=links.entry_line_id WHERE links.tenant_id=%s AND lines.entry_id=%s
               ORDER BY links.entry_line_id,dimensions.dimension_code""",
            (self.tenant_id, entry_id),
        ).fetchall()
        dimensions_by_line: dict[str, dict[str, str]] = {}
        for row in dimension_rows:
            data = _row(row, ("line_id", "dimension_code", "value_code"))
            dimensions_by_line.setdefault(str(data["line_id"]), {})[str(data["dimension_code"])] = str(
                data["value_code"]
            )
        public_lines: list[dict[str, Any]] = []
        total_debit = total_credit = 0
        columns = (
            "id",
            "line_number",
            "account_id",
            "description",
            "debit_minor",
            "credit_minor",
            "currency_code",
            "account_code",
            "account_name",
        )
        for row in line_rows:
            record = _row(row, columns)
            debit_minor, credit_minor = int(record["debit_minor"]), int(record["credit_minor"])
            total_debit += debit_minor
            total_credit += credit_minor
            record.update(
                {
                    "debit": _minor_to_text(debit_minor, minor_units),
                    "credit": _minor_to_text(credit_minor, minor_units),
                    "dimensions": dimensions_by_line.get(str(record["id"]), {}),
                }
            )
            public_lines.append(record)
        entry.update(
            {
                "currency_minor_units": minor_units,
                "total_debit_minor": total_debit,
                "total_credit_minor": total_credit,
                "total_debit": _minor_to_text(total_debit, minor_units),
                "total_credit": _minor_to_text(total_credit, minor_units),
                "balanced": total_debit > 0 and total_debit == total_credit and len(public_lines) >= 2,
                "lines": public_lines,
            }
        )
        return entry

    def _validate_entry_integrity(self, entry_id: str) -> None:
        entry = self._entry_row(entry_id)
        period = self.connection.execute(
            "SELECT start_date,end_date,status FROM reconforge.fiscal_periods WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, entry["period_id"]),
        ).fetchone()
        if period is None:
            raise PlatformError("Fiscal-period reference was not found.")
        period_data = _row(period, ("start_date", "end_date", "status"))
        if period_data["status"] != "Open":
            raise PlatformError("Ledger-control entries can be validated only while their fiscal period is Open.")
        posted_on = _iso_date(entry["posting_date"], "Stored posting date")
        if (
            not _iso_date(period_data["start_date"], "Stored period start date")
            <= posted_on
            <= _iso_date(period_data["end_date"], "Stored period end date")
        ):
            raise PlatformError("Posting date must remain inside the selected fiscal period.")
        scope = self.connection.execute(
            """SELECT organizations.active,entities.active,journals.active,charts.active,currencies.active,
                      entities.currency_code,journals.currency_code,journals.organization_code
               FROM reconforge.finance_entries entries
               JOIN reconforge.finance_journals journals ON journals.tenant_id=entries.tenant_id AND journals.id=entries.journal_id
               JOIN reconforge.finance_charts charts ON charts.tenant_id=journals.tenant_id AND charts.id=journals.chart_id
               JOIN reconforge.organizations organizations ON organizations.tenant_id=entries.tenant_id
                AND organizations.organization_code=entries.organization_code
               JOIN reconforge.legal_entities entities ON entities.tenant_id=entries.tenant_id
                AND entities.organization_id=organizations.id AND entities.entity_code=entries.entity_code
               JOIN reconforge.currencies currencies ON currencies.tenant_id=entries.tenant_id AND currencies.code=entries.currency_code
               WHERE entries.tenant_id=%s AND entries.id=%s""",
            (self.tenant_id, entry_id),
        ).fetchone()
        if scope is None:
            raise PlatformError("Ledger-control entry contains an inactive or inconsistent finance reference.")
        scope_data = _row(
            scope,
            (
                "organization_active",
                "entity_active",
                "journal_active",
                "chart_active",
                "currency_active",
                "entity_currency",
                "journal_currency",
                "journal_organization_code",
            ),
        )
        if (
            not all(
                bool(scope_data[field])
                for field in (
                    "organization_active",
                    "entity_active",
                    "journal_active",
                    "chart_active",
                    "currency_active",
                )
            )
            or scope_data["entity_currency"] != entry["currency_code"]
            or scope_data["journal_currency"] != entry["currency_code"]
            or scope_data["journal_organization_code"] != entry["organization_code"]
        ):
            raise PlatformError("Ledger-control entry contains an inactive or inconsistent finance reference.")
        totals = self.connection.execute(
            """SELECT COUNT(*),COALESCE(SUM(debit_minor),0),COALESCE(SUM(credit_minor),0)
               FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND entry_id=%s""",
            (self.tenant_id, entry_id),
        ).fetchone()
        if totals is None:
            raise PostgresFinanceCoreError("Unable to verify PostgreSQL Finance Core entry totals.")
        total_data = _row(totals, ("line_count", "debit_minor", "credit_minor"))
        if (
            int(total_data["line_count"]) < 2
            or int(total_data["debit_minor"]) <= 0
            or int(total_data["debit_minor"]) != int(total_data["credit_minor"])
            or int(total_data["debit_minor"]) != int(entry["total_debit_minor"])
        ):
            raise PlatformError("Ledger-control entry must contain at least two balanced non-zero lines.")
        invalid_account = self.connection.execute(
            """SELECT 1 FROM reconforge.finance_entry_lines lines JOIN reconforge.finance_accounts accounts
                ON accounts.tenant_id=lines.tenant_id AND accounts.id=lines.account_id
               JOIN reconforge.finance_journals journals ON journals.tenant_id=lines.tenant_id AND journals.id=%s
               WHERE lines.tenant_id=%s AND lines.entry_id=%s AND
                (accounts.chart_id<>journals.chart_id OR NOT accounts.active OR NOT accounts.allow_posting
                 OR (%s='Manual' AND NOT accounts.allow_manual_posting)) LIMIT 1""",
            (entry["journal_id"], self.tenant_id, entry_id, entry["source_type"]),
        ).fetchone()
        if invalid_account is not None:
            raise PlatformError("Ledger-control entry contains an inactive or incompatible account.")
        invalid_dimension = self.connection.execute(
            """SELECT 1 FROM reconforge.finance_entry_line_dimensions links
               JOIN reconforge.finance_dimensions dimensions ON dimensions.tenant_id=links.tenant_id AND dimensions.id=links.dimension_id
               JOIN reconforge.finance_dimension_values values_ ON values_.tenant_id=links.tenant_id AND values_.id=links.dimension_value_id
               JOIN reconforge.finance_entry_lines lines ON lines.tenant_id=links.tenant_id AND lines.id=links.entry_line_id
               WHERE links.tenant_id=%s AND lines.entry_id=%s AND
                (NOT dimensions.active OR NOT values_.active OR dimensions.workspace_id<>%s
                 OR (dimensions.organization_code<>'' AND dimensions.organization_code<>%s)
                 OR values_.dimension_id<>dimensions.id) LIMIT 1""",
            (self.tenant_id, entry_id, entry["workspace_id"], entry["organization_code"]),
        ).fetchone()
        missing_dimension = self.connection.execute(
            """SELECT 1 FROM reconforge.finance_entry_lines lines CROSS JOIN reconforge.finance_dimensions dimensions
               WHERE lines.tenant_id=%s AND lines.entry_id=%s AND dimensions.tenant_id=lines.tenant_id
                AND dimensions.workspace_id=%s AND dimensions.active=TRUE AND dimensions.required_on_entries=TRUE
                AND (dimensions.organization_code='' OR dimensions.organization_code=%s) AND NOT EXISTS (
                 SELECT 1 FROM reconforge.finance_entry_line_dimensions links WHERE links.tenant_id=lines.tenant_id
                  AND links.entry_line_id=lines.id AND links.dimension_id=dimensions.id) LIMIT 1""",
            (self.tenant_id, entry_id, entry["workspace_id"], entry["organization_code"]),
        ).fetchone()
        if invalid_dimension is not None:
            raise PlatformError("Ledger-control entry contains an inactive or cross-scope accounting dimension.")
        if missing_dimension is not None:
            raise PlatformError("Ledger-control entry is missing a required accounting dimension.")


POSTGRES_FINANCE_CORE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.finance_charts (
 tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
 id TEXT NOT NULL, workspace_id TEXT NOT NULL, organization_code TEXT NOT NULL DEFAULT '',
 chart_code TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 active BOOLEAN NOT NULL DEFAULT TRUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,workspace_id,chart_code),
 FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reconforge.finance_accounts (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL, chart_id TEXT NOT NULL,
 parent_account_id TEXT, account_code TEXT NOT NULL, name TEXT NOT NULL,
 account_type TEXT NOT NULL, normal_balance TEXT NOT NULL CHECK (normal_balance IN ('Debit','Credit')),
 allow_posting BOOLEAN NOT NULL, allow_manual_posting BOOLEAN NOT NULL,
 reconciliation_required BOOLEAN NOT NULL, active BOOLEAN NOT NULL,
 description TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,chart_id,account_code),
 FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY (tenant_id,chart_id) REFERENCES reconforge.finance_charts(tenant_id,id),
 FOREIGN KEY (tenant_id,parent_account_id) REFERENCES reconforge.finance_accounts(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS reconforge.finance_dimensions (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL,
 organization_code TEXT NOT NULL DEFAULT '', dimension_code TEXT NOT NULL, name TEXT NOT NULL,
 dimension_type TEXT NOT NULL, required_on_entries BOOLEAN NOT NULL, active BOOLEAN NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,workspace_id,dimension_code),
 FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reconforge.finance_dimension_values (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL, dimension_id TEXT NOT NULL,
 value_code TEXT NOT NULL, name TEXT NOT NULL, active BOOLEAN NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,dimension_id,value_code),
 FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY (tenant_id,dimension_id) REFERENCES reconforge.finance_dimensions(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS reconforge.finance_journals (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL, chart_id TEXT NOT NULL,
 organization_code TEXT NOT NULL, journal_code TEXT NOT NULL, name TEXT NOT NULL,
 currency_code TEXT NOT NULL, journal_type TEXT NOT NULL, active BOOLEAN NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,workspace_id,organization_code,journal_code),
 FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY (tenant_id,chart_id) REFERENCES reconforge.finance_charts(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS reconforge.finance_entries (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL, journal_id TEXT NOT NULL,
 organization_code TEXT NOT NULL, entity_code TEXT NOT NULL, period_id TEXT NOT NULL,
 entry_number TEXT NOT NULL, posting_date TEXT NOT NULL, description TEXT NOT NULL,
 external_reference TEXT NOT NULL DEFAULT '', source_type TEXT NOT NULL,
 status TEXT NOT NULL CHECK (status IN ('Draft','Validated','Voided')),
 currency_code TEXT NOT NULL, total_debit_minor BIGINT NOT NULL CHECK (total_debit_minor >= 0),
 total_credit_minor BIGINT NOT NULL CHECK (total_credit_minor >= 0), created_by TEXT NOT NULL,
 validated_by TEXT, voided_by TEXT, validation_reason TEXT NOT NULL DEFAULT '',
 void_reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 validated_at TEXT, voided_at TEXT, PRIMARY KEY (tenant_id,id),
 UNIQUE (tenant_id,workspace_id,entry_number),
 CHECK (total_debit_minor = total_credit_minor),
 FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY (tenant_id,journal_id) REFERENCES reconforge.finance_journals(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS reconforge.finance_entry_lines (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, entry_id TEXT NOT NULL, line_number INTEGER NOT NULL CHECK (line_number > 0),
 account_id TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', debit_minor BIGINT NOT NULL CHECK (debit_minor >= 0),
 credit_minor BIGINT NOT NULL CHECK (credit_minor >= 0), currency_code TEXT NOT NULL,
 CHECK ((debit_minor = 0) <> (credit_minor = 0)), PRIMARY KEY (tenant_id,id),
 UNIQUE (tenant_id,entry_id,line_number),
 FOREIGN KEY (tenant_id,entry_id) REFERENCES reconforge.finance_entries(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY (tenant_id,account_id) REFERENCES reconforge.finance_accounts(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS reconforge.finance_entry_line_dimensions (
 tenant_id TEXT NOT NULL, entry_line_id TEXT NOT NULL, dimension_id TEXT NOT NULL, dimension_value_id TEXT NOT NULL,
 PRIMARY KEY (tenant_id,entry_line_id,dimension_id),
 FOREIGN KEY (tenant_id,entry_line_id) REFERENCES reconforge.finance_entry_lines(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY (tenant_id,dimension_id) REFERENCES reconforge.finance_dimensions(tenant_id,id),
 FOREIGN KEY (tenant_id,dimension_value_id) REFERENCES reconforge.finance_dimension_values(tenant_id,id)
);
CREATE INDEX IF NOT EXISTS idx_finance_entries_scope ON reconforge.finance_entries(tenant_id,workspace_id,organization_code,entity_code,period_id,status);
CREATE INDEX IF NOT EXISTS idx_finance_lines_entry ON reconforge.finance_entry_lines(tenant_id,entry_id,line_number);
DO $reconforge$
DECLARE table_name text;
BEGIN
 FOREACH table_name IN ARRAY ARRAY['finance_charts','finance_accounts','finance_dimensions','finance_dimension_values','finance_journals','finance_entries','finance_entry_lines','finance_entry_line_dimensions'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY', table_name);
  EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY', table_name);
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope') THEN
   EXECUTE format('CREATE POLICY tenant_scope ON reconforge.%I USING (tenant_id = current_setting(''app.tenant_id'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))', table_name);
  END IF;
 END LOOP;
END $reconforge$;
"""


def install_postgres_finance_core_schema(connection: Any) -> None:
    """Install additive, tenant-scoped Finance Core tables."""

    connection.execute(POSTGRES_FINANCE_CORE_SCHEMA_SQL)
