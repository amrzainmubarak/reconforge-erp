"""Tenant-scoped PostgreSQL schema for the governed Payables contract."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from reconforge.application.payables import (
    PurchaseOrderLineInput,
    SupplierInvoiceLineInput,
    ThreeWayMatchResult,
)
from reconforge.auth.rbac import same_actor
from reconforge.domain.models import utc_now_text
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.io.persisted import (
    PersistedJsonError,
    decode_financial_idempotency_response,
    encode_financial_idempotency_response,
    encode_postgres_outbox_payload,
)
from reconforge.platform.common import PlatformError, platform_id

_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,63}$")
SUPPLIER_STATUSES = ("Draft", "Active", "Suspended", "Closed")
INVOICE_STATUSES = ("Draft", "Submitted", "Matched", "Exception", "Approved", "Paid", "Rejected")


class PostgresPayablesError(RuntimeError):
    """Safe tenant-scoped Payables persistence failure."""


def _row(value: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    if isinstance(value, Mapping):
        result = {column: value[column] for column in columns}
    else:
        result = dict(zip(columns, value, strict=True))
    return {key: item.isoformat() if isinstance(item, (date, datetime)) else item for key, item in result.items()}


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


def _choice(value: object, label: str, choices: tuple[str, ...]) -> str:
    candidate = _text(value, label, maximum=40)
    selected = {choice.lower(): choice for choice in choices}.get(candidate.lower())
    if selected is None:
        raise PlatformError(f"{label} must be one of: {', '.join(choices)}.")
    return selected


def _iso_date(value: object, label: str, *, required: bool = True) -> date | None:
    raw = _text(value, label, maximum=10, required=required)
    if not raw:
        return None
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise PlatformError(f"{label} must use YYYY-MM-DD format.") from exc
    if parsed.isoformat() != raw:
        raise PlatformError(f"{label} must use YYYY-MM-DD format.")
    return parsed


def _minor(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise PlatformError(f"{label} must be a non-negative integer minor-unit value.")
    try:
        result = value if isinstance(value, int) else int(str(value).strip())
    except (TypeError, ValueError, OverflowError) as exc:
        raise PlatformError(f"{label} must be a non-negative integer minor-unit value.") from exc
    if result < 0 or result > 9_000_000_000_000_000_000:
        raise PlatformError(f"{label} must be a supported non-negative integer minor-unit value.")
    return result


def _quantity(value: object, label: str) -> tuple[Decimal, str]:
    raw = _text(value, label, maximum=80)
    try:
        quantity = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise PlatformError(f"{label} must be an exact decimal quantity.") from exc
    if not quantity.is_finite() or quantity <= 0:
        raise PlatformError(f"{label} must be finite and greater than zero.")
    exponent = quantity.as_tuple().exponent
    if not isinstance(exponent, int):
        raise PlatformError(f"{label} must be an exact decimal quantity.")
    normalized = quantity.normalize()
    text = "0" if normalized == 0 else format(normalized, "f")
    return quantity, text


def _normalize_po_lines(lines: Sequence[PurchaseOrderLineInput]) -> list[tuple[str, Decimal, str, int, str, int]]:
    if not lines:
        raise PlatformError("Purchase order requires at least one line.")
    if len(lines) > 1_000:
        raise PlatformError("Purchase order supports at most 1000 lines.")
    result: list[tuple[str, Decimal, str, int, str, int]] = []
    for index, line in enumerate(lines, start=1):
        item_code = _code(line.item_code, f"Purchase-order line {index} item code")
        quantity, quantity_text = _quantity(line.ordered_quantity, f"Purchase-order line {index} quantity")
        result.append(
            (
                item_code,
                quantity,
                quantity_text,
                _minor(line.unit_price_minor, f"Purchase-order line {index} unit price"),
                _text(line.description, f"Purchase-order line {index} description", maximum=500, required=False),
                _minor(line.tax_minor, f"Purchase-order line {index} tax"),
            )
        )
    return result


def _normalize_invoice_lines(
    lines: Sequence[SupplierInvoiceLineInput],
) -> list[tuple[str, Decimal, str, int, int, str, int]]:
    if not lines:
        raise PlatformError("Supplier invoice requires at least one line.")
    if len(lines) > 1_000:
        raise PlatformError("Supplier invoice supports at most 1000 lines.")
    result: list[tuple[str, Decimal, str, int, int, str, int]] = []
    for index, line in enumerate(lines, start=1):
        po_line_id = _text(
            line.purchase_order_line_id,
            f"Supplier-invoice line {index} purchase-order line id",
            maximum=128,
        )
        quantity, quantity_text = _quantity(line.invoiced_quantity, f"Supplier-invoice line {index} quantity")
        result.append(
            (
                po_line_id,
                quantity,
                quantity_text,
                _minor(line.unit_price_minor, f"Supplier-invoice line {index} unit price"),
                _minor(line.line_total_minor, f"Supplier-invoice line {index} total"),
                _text(line.description, f"Supplier-invoice line {index} description", maximum=500, required=False),
                _minor(line.tax_minor, f"Supplier-invoice line {index} tax"),
            )
        )
    return result


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _rounded_minor(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


POSTGRES_PAYABLES_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.ap_suppliers (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL,
    organization_id TEXT, legal_entity_id TEXT, supplier_code TEXT NOT NULL,
    name TEXT NOT NULL, currency_code TEXT NOT NULL, tax_identifier TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Draft','Active','Suspended','Closed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_version BIGINT NOT NULL DEFAULT 1 CHECK (row_version > 0),
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,workspace_id,supplier_code),
    FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,currency_code) REFERENCES reconforge.currencies(tenant_id,code) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS reconforge.ap_purchase_orders (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL,
    organization_id TEXT, legal_entity_id TEXT, branch_id TEXT, supplier_id TEXT NOT NULL,
    po_number TEXT NOT NULL, order_date DATE NOT NULL, expected_date DATE, currency_code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft','Submitted','Approved','Closed','Cancelled')),
    created_by TEXT NOT NULL DEFAULT '', approved_by TEXT NOT NULL DEFAULT '', approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_version BIGINT NOT NULL DEFAULT 1 CHECK (row_version > 0),
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,workspace_id,po_number),
    FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,supplier_id) REFERENCES reconforge.ap_suppliers(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,branch_id) REFERENCES reconforge.branches(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,currency_code) REFERENCES reconforge.currencies(tenant_id,code) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS reconforge.ap_purchase_order_lines (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, purchase_order_id TEXT NOT NULL,
    line_number INTEGER NOT NULL CHECK (line_number > 0), item_code TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '', ordered_quantity NUMERIC NOT NULL CHECK (ordered_quantity > 0),
    ordered_quantity_text TEXT NOT NULL, unit_price_minor BIGINT NOT NULL CHECK (unit_price_minor >= 0),
    tax_minor BIGINT NOT NULL DEFAULT 0 CHECK (tax_minor >= 0), created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,purchase_order_id,line_number),
    FOREIGN KEY (tenant_id,purchase_order_id) REFERENCES reconforge.ap_purchase_orders(tenant_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reconforge.ap_goods_receipts (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL, purchase_order_id TEXT NOT NULL,
    receipt_number TEXT NOT NULL, receipt_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'Posted' CHECK (status IN ('Draft','Posted','Cancelled')),
    created_by TEXT NOT NULL DEFAULT '', posted_by TEXT NOT NULL DEFAULT '', posted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,workspace_id,receipt_number),
    FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,purchase_order_id) REFERENCES reconforge.ap_purchase_orders(tenant_id,id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS reconforge.ap_goods_receipt_lines (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, receipt_id TEXT NOT NULL, purchase_order_line_id TEXT NOT NULL,
    received_quantity NUMERIC NOT NULL CHECK (received_quantity > 0), received_quantity_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id),
    UNIQUE (tenant_id,receipt_id,purchase_order_line_id),
    FOREIGN KEY (tenant_id,receipt_id) REFERENCES reconforge.ap_goods_receipts(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,purchase_order_line_id) REFERENCES reconforge.ap_purchase_order_lines(tenant_id,id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS reconforge.ap_supplier_invoices (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL,
    organization_id TEXT, legal_entity_id TEXT, supplier_id TEXT NOT NULL, purchase_order_id TEXT,
    invoice_number TEXT NOT NULL, invoice_date DATE NOT NULL, due_date DATE, currency_code TEXT NOT NULL,
    tax_minor BIGINT NOT NULL DEFAULT 0 CHECK (tax_minor >= 0), total_minor BIGINT NOT NULL CHECK (total_minor >= 0),
    status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft','Submitted','Matched','Exception','Approved','Paid','Rejected')),
    created_by TEXT NOT NULL DEFAULT '', approved_by TEXT NOT NULL DEFAULT '', approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_version BIGINT NOT NULL DEFAULT 1 CHECK (row_version > 0),
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,workspace_id,supplier_id,invoice_number),
    FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,supplier_id) REFERENCES reconforge.ap_suppliers(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,purchase_order_id) REFERENCES reconforge.ap_purchase_orders(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,currency_code) REFERENCES reconforge.currencies(tenant_id,code) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS reconforge.ap_supplier_invoice_lines (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, supplier_invoice_id TEXT NOT NULL, purchase_order_line_id TEXT,
    line_number INTEGER NOT NULL CHECK (line_number > 0), description TEXT NOT NULL DEFAULT '',
    invoiced_quantity NUMERIC NOT NULL CHECK (invoiced_quantity > 0), invoiced_quantity_text TEXT NOT NULL,
    unit_price_minor BIGINT NOT NULL CHECK (unit_price_minor >= 0), tax_minor BIGINT NOT NULL DEFAULT 0 CHECK (tax_minor >= 0),
    line_total_minor BIGINT NOT NULL CHECK (line_total_minor >= 0), created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,supplier_invoice_id,line_number),
    FOREIGN KEY (tenant_id,supplier_invoice_id) REFERENCES reconforge.ap_supplier_invoices(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,purchase_order_line_id) REFERENCES reconforge.ap_purchase_order_lines(tenant_id,id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS reconforge.ap_three_way_matches (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL, supplier_invoice_id TEXT NOT NULL,
    purchase_order_id TEXT, status TEXT NOT NULL CHECK (status IN ('Passed','Exception')),
    quantity_variance NUMERIC NOT NULL DEFAULT 0, quantity_variance_text TEXT NOT NULL DEFAULT '0',
    price_variance_minor BIGINT NOT NULL DEFAULT 0, total_variance_minor BIGINT NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,supplier_invoice_id),
    FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,supplier_invoice_id) REFERENCES reconforge.ap_supplier_invoices(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,purchase_order_id) REFERENCES reconforge.ap_purchase_orders(tenant_id,id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS reconforge.ap_idempotency_keys (
    tenant_id TEXT NOT NULL, scope TEXT NOT NULL, idempotency_key TEXT NOT NULL,
    response_json JSONB NOT NULL CHECK (jsonb_typeof(response_json) = 'object'), created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,scope,idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_ap_purchase_orders_supplier ON reconforge.ap_purchase_orders(tenant_id,workspace_id,supplier_id,status,order_date,id);
CREATE INDEX IF NOT EXISTS idx_ap_supplier_invoices_supplier ON reconforge.ap_supplier_invoices(tenant_id,workspace_id,supplier_id,status,invoice_date,id);
CREATE INDEX IF NOT EXISTS idx_ap_receipt_lines_po_line ON reconforge.ap_goods_receipt_lines(tenant_id,purchase_order_line_id,receipt_id);
CREATE INDEX IF NOT EXISTS idx_ap_invoice_lines_po_line ON reconforge.ap_supplier_invoice_lines(tenant_id,purchase_order_line_id,supplier_invoice_id);
DO $rls$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['ap_suppliers','ap_purchase_orders','ap_purchase_order_lines','ap_goods_receipts','ap_goods_receipt_lines','ap_supplier_invoices','ap_supplier_invoice_lines','ap_three_way_matches','ap_idempotency_keys']
    LOOP
        EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I', table_name);
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope') THEN
            EXECUTE format('CREATE POLICY tenant_isolation ON reconforge.%I USING (tenant_id = current_setting(''app.tenant_id'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))', table_name);
        END IF;
    END LOOP;
END
$rls$;
"""


def install_postgres_payables_schema(connection: Any, tenant_id: str) -> None:
    """Install the additive Payables schema under one explicit tenant scope."""

    with connection.transaction():
        set_local_tenant_scope(connection, tenant_id)
        connection.execute(POSTGRES_PAYABLES_SCHEMA_SQL)


class PostgresPayablesRepository:
    """Build the complete Payables contract on one forced-RLS tenant boundary."""

    _SUPPLIER_COLUMNS = (
        "id",
        "workspace_id",
        "organization_id",
        "legal_entity_id",
        "supplier_code",
        "name",
        "currency_code",
        "tax_identifier",
        "status",
        "created_at",
        "updated_at",
        "row_version",
    )
    _PO_COLUMNS = (
        "id",
        "workspace_id",
        "organization_id",
        "legal_entity_id",
        "branch_id",
        "supplier_id",
        "po_number",
        "order_date",
        "expected_date",
        "currency_code",
        "status",
        "created_by",
        "approved_by",
        "approved_at",
        "created_at",
        "updated_at",
        "row_version",
    )
    _PO_LINE_COLUMNS = (
        "id",
        "purchase_order_id",
        "line_number",
        "item_code",
        "description",
        "ordered_quantity",
        "unit_price_minor",
        "tax_minor",
        "created_at",
    )
    _RECEIPT_COLUMNS = (
        "id",
        "workspace_id",
        "purchase_order_id",
        "receipt_number",
        "receipt_date",
        "status",
        "created_by",
        "posted_by",
        "posted_at",
        "created_at",
        "updated_at",
    )
    _RECEIPT_LINE_COLUMNS = (
        "id",
        "receipt_id",
        "purchase_order_line_id",
        "received_quantity",
        "created_at",
    )
    _INVOICE_COLUMNS = (
        "id",
        "workspace_id",
        "organization_id",
        "legal_entity_id",
        "supplier_id",
        "purchase_order_id",
        "invoice_number",
        "invoice_date",
        "due_date",
        "currency_code",
        "tax_minor",
        "total_minor",
        "status",
        "created_by",
        "approved_by",
        "approved_at",
        "created_at",
        "updated_at",
        "row_version",
    )
    _INVOICE_LINE_COLUMNS = (
        "id",
        "supplier_invoice_id",
        "purchase_order_line_id",
        "line_number",
        "description",
        "invoiced_quantity",
        "unit_price_minor",
        "tax_minor",
        "line_total_minor",
        "created_at",
    )
    _MATCH_COLUMNS = (
        "id",
        "workspace_id",
        "supplier_invoice_id",
        "purchase_order_id",
        "status",
        "quantity_variance",
        "price_variance_minor",
        "total_variance_minor",
        "reason",
        "created_at",
        "updated_at",
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
        except (PlatformError, PostgresPayablesError):
            raise
        except Exception as exc:
            raise PostgresPayablesError("PostgreSQL Payables operation failed.") from exc

    def _workspace_id(self, workspace: str, *, required: bool = True) -> str | None:
        row = self.connection.execute(
            "SELECT id FROM reconforge.domain_workspaces WHERE tenant_id=%s AND name=%s",
            (self.tenant_id, _text(workspace, "Workspace name")),
        ).fetchone()
        if row is None:
            if required:
                raise PostgresPayablesError("Payables workspace was not found for this tenant.")
            return None
        return str(row["id"] if isinstance(row, Mapping) else row[0])

    def _scope_ids(
        self,
        workspace_id: str,
        *,
        organization_code: str,
        entity_code: str,
    ) -> tuple[str | None, str | None]:
        organization_id: str | None = None
        entity_id: str | None = None
        if organization_code.strip():
            code = _code(organization_code, "Organization code")
            row = self.connection.execute(
                """SELECT o.id FROM reconforge.organizations o
                   JOIN reconforge.master_data_workspace_organizations w
                     ON w.tenant_id=o.tenant_id AND w.organization_id=o.id
                   WHERE o.tenant_id=%s AND w.workspace_id=%s
                     AND o.organization_code=%s AND o.active=TRUE""",
                (self.tenant_id, workspace_id, code),
            ).fetchone()
            if row is None:
                raise PlatformError("Payables organization was not found or inactive in this workspace.")
            organization_id = str(row["id"] if isinstance(row, Mapping) else row[0])
        if entity_code.strip():
            if organization_id is None:
                raise PlatformError("Organization code is required when an entity code is supplied.")
            code = _code(entity_code, "Entity code")
            row = self.connection.execute(
                """SELECT id FROM reconforge.legal_entities
                   WHERE tenant_id=%s AND organization_id=%s AND entity_code=%s AND active=TRUE""",
                (self.tenant_id, organization_id, code),
            ).fetchone()
            if row is None:
                raise PlatformError("Payables legal entity was not found or inactive.")
            entity_id = str(row["id"] if isinstance(row, Mapping) else row[0])
        return organization_id, entity_id

    def _event(
        self,
        *,
        actor_label: str,
        object_type: str,
        object_id: str,
        action: str,
        metadata: dict[str, Any],
        version: object = "",
    ) -> None:
        try:
            payload = encode_postgres_outbox_payload(metadata).text
        except PersistedJsonError as exc:
            raise PostgresPayablesError("Payables event payload is invalid.") from exc
        event_id = platform_id("OBX", action, object_id, version)
        self.connection.execute(
            """INSERT INTO reconforge.outbox_events
               (tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload)
               VALUES (%s,%s,%s,%s,%s,CAST(%s AS jsonb))
               ON CONFLICT (tenant_id,event_id) DO NOTHING""",
            (self.tenant_id, event_id, action, object_type, object_id, payload),
        )
        PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=actor_label,
            object_type=object_type,
            object_id=object_id,
            action=action,
            metadata=metadata,
        )

    def _supplier_by_code(self, workspace_id: str, supplier_code: str) -> dict[str, Any]:
        row = self.connection.execute(
            """SELECT id,workspace_id,organization_id,legal_entity_id,supplier_code,name,
                      currency_code,tax_identifier,status,created_at,updated_at,row_version
               FROM reconforge.ap_suppliers
               WHERE tenant_id=%s AND workspace_id=%s AND supplier_code=%s""",
            (self.tenant_id, workspace_id, _code(supplier_code, "Supplier code")),
        ).fetchone()
        if row is None:
            raise PlatformError("Supplier not found in the requested workspace.")
        supplier = _row(row, self._SUPPLIER_COLUMNS)
        if supplier["status"] != "Active":
            raise PlatformError("Supplier must be active.")
        return supplier

    def _branch_id(self, organization_id: str | None, entity_id: str | None, branch_code: str) -> str | None:
        if not branch_code.strip():
            return None
        if organization_id is None:
            raise PlatformError("Organization code is required when a branch code is supplied.")
        row = self.connection.execute(
            """SELECT id FROM reconforge.branches
               WHERE tenant_id=%s AND organization_id=%s AND branch_code=%s AND active=TRUE
                 AND (%s IS NULL OR legal_entity_id=%s)""",
            (self.tenant_id, organization_id, _code(branch_code, "Branch code"), entity_id, entity_id),
        ).fetchone()
        if row is None:
            raise PlatformError("Payables branch was not found or inactive.")
        return str(row["id"] if isinstance(row, Mapping) else row[0])

    def _idempotent(self, operation: str, workspace_id: str, key: str) -> dict[str, Any] | None:
        normalized = _text(key, "Idempotency key", maximum=200, required=False)
        if not normalized:
            return None
        row = self.connection.execute(
            """SELECT response_json FROM reconforge.ap_idempotency_keys
               WHERE tenant_id=%s AND scope=%s AND idempotency_key=%s""",
            (self.tenant_id, f"{operation}:{workspace_id}", normalized),
        ).fetchone()
        if row is None:
            return None
        raw = row["response_json"] if isinstance(row, Mapping) else row[0]
        try:
            return decode_financial_idempotency_response(raw).payload
        except PersistedJsonError as exc:
            raise PostgresPayablesError("Stored Payables idempotency response is invalid.") from exc

    def _save_idempotency(self, operation: str, workspace_id: str, key: str, result: dict[str, Any]) -> None:
        normalized = _text(key, "Idempotency key", maximum=200, required=False)
        if not normalized:
            return
        try:
            document = encode_financial_idempotency_response(result)
        except PersistedJsonError as exc:
            raise PostgresPayablesError("Payables idempotency response is invalid.") from exc
        self.connection.execute(
            """INSERT INTO reconforge.ap_idempotency_keys
               (tenant_id,scope,idempotency_key,response_json)
               VALUES (%s,%s,%s,CAST(%s AS jsonb))""",
            (self.tenant_id, f"{operation}:{workspace_id}", normalized, document.text),
        )

    def _purchase_order(self, purchase_order_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            """SELECT id,workspace_id,organization_id,legal_entity_id,branch_id,supplier_id,
                      po_number,order_date,expected_date,currency_code,status,created_by,
                      approved_by,approved_at,created_at,updated_at,row_version
               FROM reconforge.ap_purchase_orders WHERE tenant_id=%s AND id=%s""",
            (self.tenant_id, _text(purchase_order_id, "Purchase order id", maximum=128)),
        ).fetchone()
        if row is None:
            raise PlatformError("Purchase order not found.")
        result = _row(row, self._PO_COLUMNS)
        lines = self.connection.execute(
            """SELECT id,purchase_order_id,line_number,item_code,description,
                      ordered_quantity_text AS ordered_quantity,unit_price_minor,tax_minor,created_at
               FROM reconforge.ap_purchase_order_lines
               WHERE tenant_id=%s AND purchase_order_id=%s ORDER BY line_number,id""",
            (self.tenant_id, purchase_order_id),
        ).fetchall()
        result["lines"] = [_row(line, self._PO_LINE_COLUMNS) for line in lines]
        return result

    def _received_quantity(self, purchase_order_line_id: str) -> Decimal:
        row = self.connection.execute(
            """SELECT COALESCE(SUM(l.received_quantity),0) AS quantity
               FROM reconforge.ap_goods_receipt_lines l
               JOIN reconforge.ap_goods_receipts r
                 ON r.tenant_id=l.tenant_id AND r.id=l.receipt_id
               WHERE l.tenant_id=%s AND l.purchase_order_line_id=%s AND r.status='Posted'""",
            (self.tenant_id, purchase_order_line_id),
        ).fetchone()
        if row is None:
            return Decimal("0")
        value = row["quantity"] if isinstance(row, Mapping) else row[0]
        return Decimal(str(value))

    def _receipt(self, receipt_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            """SELECT id,workspace_id,purchase_order_id,receipt_number,receipt_date,status,
                      created_by,posted_by,posted_at,created_at,updated_at
               FROM reconforge.ap_goods_receipts WHERE tenant_id=%s AND id=%s""",
            (self.tenant_id, _text(receipt_id, "Receipt id", maximum=128)),
        ).fetchone()
        if row is None:
            raise PlatformError("Goods receipt not found.")
        result = _row(row, self._RECEIPT_COLUMNS)
        lines = self.connection.execute(
            """SELECT id,receipt_id,purchase_order_line_id,
                      received_quantity_text AS received_quantity,created_at
               FROM reconforge.ap_goods_receipt_lines
               WHERE tenant_id=%s AND receipt_id=%s ORDER BY id""",
            (self.tenant_id, receipt_id),
        ).fetchall()
        result["lines"] = [_row(line, self._RECEIPT_LINE_COLUMNS) for line in lines]
        return result

    def _supplier_invoice(self, invoice_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            """SELECT id,workspace_id,organization_id,legal_entity_id,supplier_id,purchase_order_id,
                      invoice_number,invoice_date,due_date,currency_code,tax_minor,total_minor,status,
                      created_by,approved_by,approved_at,created_at,updated_at,row_version
               FROM reconforge.ap_supplier_invoices WHERE tenant_id=%s AND id=%s""",
            (self.tenant_id, _text(invoice_id, "Supplier invoice id", maximum=128)),
        ).fetchone()
        if row is None:
            raise PlatformError("Supplier invoice not found.")
        result = _row(row, self._INVOICE_COLUMNS)
        lines = self.connection.execute(
            """SELECT id,supplier_invoice_id,purchase_order_line_id,line_number,description,
                      invoiced_quantity_text AS invoiced_quantity,unit_price_minor,tax_minor,
                      line_total_minor,created_at
               FROM reconforge.ap_supplier_invoice_lines
               WHERE tenant_id=%s AND supplier_invoice_id=%s ORDER BY line_number,id""",
            (self.tenant_id, invoice_id),
        ).fetchall()
        result["lines"] = [_row(line, self._INVOICE_LINE_COLUMNS) for line in lines]
        match = self.connection.execute(
            """SELECT id,workspace_id,supplier_invoice_id,purchase_order_id,status,
                      quantity_variance_text AS quantity_variance,price_variance_minor,
                      total_variance_minor,reason,created_at,updated_at
               FROM reconforge.ap_three_way_matches
               WHERE tenant_id=%s AND supplier_invoice_id=%s""",
            (self.tenant_id, invoice_id),
        ).fetchone()
        result["three_way_match"] = _row(match, self._MATCH_COLUMNS) if match is not None else None
        return result

    def upsert_supplier(
        self,
        *,
        supplier_code: str,
        name: str,
        currency_code: str,
        workspace: str = "default",
        organization_code: str = "",
        entity_code: str = "",
        tax_identifier: str = "",
        status: str = "Active",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        code = _code(supplier_code, "Supplier code")
        currency = _code(currency_code, "Currency code")
        if len(currency) != 3 or not currency.isalpha():
            raise PlatformError("Currency code must be a three-letter alphabetic code.")
        supplier_status = _choice(status, "Supplier status", SUPPLIER_STATUSES)
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            if workspace_id is None:
                raise PostgresPayablesError("Payables workspace was not found for this tenant.")
            if (
                self.connection.execute(
                    "SELECT 1 FROM reconforge.currencies WHERE tenant_id=%s AND code=%s AND active=TRUE",
                    (self.tenant_id, currency),
                ).fetchone()
                is None
            ):
                raise PlatformError("Payables currency was not found or inactive.")
            organization_id, entity_id = self._scope_ids(
                workspace_id,
                organization_code=organization_code,
                entity_code=entity_code,
            )
            supplier_id = platform_id("SUP", workspace_id, code)
            row = self.connection.execute(
                """INSERT INTO reconforge.ap_suppliers
                   (tenant_id,id,workspace_id,organization_id,legal_entity_id,supplier_code,
                    name,currency_code,tax_identifier,status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (tenant_id,workspace_id,supplier_code) DO UPDATE SET
                    organization_id=excluded.organization_id,legal_entity_id=excluded.legal_entity_id,
                    name=excluded.name,currency_code=excluded.currency_code,
                    tax_identifier=excluded.tax_identifier,status=excluded.status,
                    updated_at=now(),row_version=ap_suppliers.row_version+1
                   RETURNING id,workspace_id,organization_id,legal_entity_id,supplier_code,name,
                    currency_code,tax_identifier,status,created_at,updated_at,row_version""",
                (
                    self.tenant_id,
                    supplier_id,
                    workspace_id,
                    organization_id,
                    entity_id,
                    code,
                    _text(name, "Supplier name"),
                    currency,
                    _text(tax_identifier, "Tax identifier", maximum=128, required=False),
                    supplier_status,
                ),
            ).fetchone()
            if row is None:
                raise PostgresPayablesError("Supplier was not found after persistence.")
            record = _row(row, self._SUPPLIER_COLUMNS)
            self._event(
                actor_label=actor_label,
                object_type="ap_supplier",
                object_id=str(record["id"]),
                action="ap_supplier_saved",
                version=record["row_version"],
                metadata={"supplier_code": code, "status": supplier_status},
            )
            return record

    def get_supplier(self, supplier_id: str) -> dict[str, Any]:
        with self._transaction():
            row = self.connection.execute(
                """SELECT id,workspace_id,organization_id,legal_entity_id,supplier_code,name,
                          currency_code,tax_identifier,status,created_at,updated_at,row_version
                   FROM reconforge.ap_suppliers WHERE tenant_id=%s AND id=%s""",
                (self.tenant_id, _text(supplier_id, "Supplier id", maximum=128)),
            ).fetchone()
            if row is None:
                raise PlatformError("Supplier not found.")
            return _row(row, self._SUPPLIER_COLUMNS)

    def list_suppliers(self, *, workspace: str = "default", status: str = "") -> list[dict[str, Any]]:
        normalized_status = _choice(status, "Supplier status", SUPPLIER_STATUSES) if status.strip() else ""
        with self._transaction():
            workspace_id = self._workspace_id(workspace, required=False)
            if workspace_id is None:
                return []
            rows = self.connection.execute(
                """SELECT id,workspace_id,organization_id,legal_entity_id,supplier_code,name,
                          currency_code,tax_identifier,status,created_at,updated_at,row_version
                   FROM reconforge.ap_suppliers
                   WHERE tenant_id=%s AND workspace_id=%s AND (%s='' OR status=%s)
                   ORDER BY supplier_code,id""",
                (self.tenant_id, workspace_id, normalized_status, normalized_status),
            ).fetchall()
            return [_row(row, self._SUPPLIER_COLUMNS) for row in rows]

    def create_purchase_order(
        self,
        *,
        po_number: str,
        supplier_code: str,
        order_date: str,
        currency_code: str,
        lines: Sequence[PurchaseOrderLineInput],
        workspace: str = "default",
        organization_code: str = "",
        entity_code: str = "",
        branch_code: str = "",
        expected_date: str = "",
        idempotency_key: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        number = _code(po_number, "Purchase order number")
        currency = _code(currency_code, "Currency code")
        if len(currency) != 3 or not currency.isalpha():
            raise PlatformError("Currency code must be a three-letter alphabetic code.")
        ordered_on = _iso_date(order_date, "Order date")
        expected_on = _iso_date(expected_date, "Expected date", required=False)
        normalized_lines = _normalize_po_lines(lines)
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            if workspace_id is None:
                raise PostgresPayablesError("Payables workspace was not found for this tenant.")
            previous = self._idempotent("purchase_order", workspace_id, idempotency_key)
            if previous is not None:
                return previous
            supplier = self._supplier_by_code(workspace_id, supplier_code)
            if supplier["currency_code"] != currency:
                raise PlatformError("Purchase order currency must match the supplier currency.")
            organization_id, entity_id = self._scope_ids(
                workspace_id,
                organization_code=organization_code,
                entity_code=entity_code,
            )
            branch_id = self._branch_id(organization_id, entity_id, branch_code)
            po_id = platform_id("APPO", workspace_id, number)
            row = self.connection.execute(
                """INSERT INTO reconforge.ap_purchase_orders
                   (tenant_id,id,workspace_id,organization_id,legal_entity_id,branch_id,
                    supplier_id,po_number,order_date,expected_date,currency_code,status,created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Draft',%s)
                   RETURNING id,workspace_id,organization_id,legal_entity_id,branch_id,supplier_id,
                    po_number,order_date,expected_date,currency_code,status,created_by,
                    approved_by,approved_at,created_at,updated_at,row_version""",
                (
                    self.tenant_id,
                    po_id,
                    workspace_id,
                    organization_id,
                    entity_id,
                    branch_id,
                    supplier["id"],
                    number,
                    ordered_on,
                    expected_on,
                    currency,
                    _text(actor_label, "Actor label", maximum=160),
                ),
            ).fetchone()
            if row is None:
                raise PostgresPayablesError("Purchase order was not found after persistence.")
            for line_number, (item_code, quantity, quantity_text, unit_price, description, tax) in enumerate(
                normalized_lines, start=1
            ):
                self.connection.execute(
                    """INSERT INTO reconforge.ap_purchase_order_lines
                       (tenant_id,id,purchase_order_id,line_number,item_code,description,
                        ordered_quantity,ordered_quantity_text,unit_price_minor,tax_minor)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        self.tenant_id,
                        platform_id("APPOL", po_id, line_number, item_code),
                        po_id,
                        line_number,
                        item_code,
                        description,
                        quantity,
                        quantity_text,
                        unit_price,
                        tax,
                    ),
                )
            result = self._purchase_order(po_id)
            self._save_idempotency("purchase_order", workspace_id, idempotency_key, result)
            self._event(
                actor_label=actor_label,
                object_type="ap_purchase_order",
                object_id=po_id,
                action="ap_purchase_order_created",
                metadata={
                    "po_number": number,
                    "supplier_id": str(supplier["id"]),
                    "line_count": len(normalized_lines),
                },
            )
            return result

    def submit_purchase_order(
        self,
        purchase_order_id: str,
        *,
        expected_version: int,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 1:
            raise PlatformError("Expected version must be a positive integer.")
        with self._transaction():
            row = self.connection.execute(
                """UPDATE reconforge.ap_purchase_orders
                   SET status='Submitted',updated_at=now(),row_version=row_version+1
                   WHERE tenant_id=%s AND id=%s AND status='Draft' AND row_version=%s
                   RETURNING row_version""",
                (self.tenant_id, _text(purchase_order_id, "Purchase order id", maximum=128), expected_version),
            ).fetchone()
            if row is None:
                raise PlatformError("Purchase order changed concurrently or is not ready for submission.")
            result = self._purchase_order(purchase_order_id)
            self._event(
                actor_label=actor_label,
                object_type="ap_purchase_order",
                object_id=purchase_order_id,
                action="ap_purchase_order_submitted",
                version=result["row_version"],
                metadata={"from_status": "Draft", "to_status": "Submitted"},
            )
            return result

    def approve_purchase_order(
        self,
        purchase_order_id: str,
        *,
        expected_version: int,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 1:
            raise PlatformError("Expected version must be a positive integer.")
        with self._transaction():
            current = self._purchase_order(purchase_order_id)
            if same_actor(current.get("created_by"), actor_label):
                raise PlatformError(
                    "Separation of duties conflict: purchase-order creator cannot approve the same order."
                )
            row = self.connection.execute(
                """UPDATE reconforge.ap_purchase_orders
                   SET status='Approved',approved_by=%s,approved_at=now(),updated_at=now(),row_version=row_version+1
                   WHERE tenant_id=%s AND id=%s AND status='Submitted' AND row_version=%s
                   RETURNING row_version""",
                (
                    _text(actor_label, "Actor label", maximum=160),
                    self.tenant_id,
                    purchase_order_id,
                    expected_version,
                ),
            ).fetchone()
            if row is None:
                raise PlatformError("Purchase order changed concurrently or is not ready for approval.")
            result = self._purchase_order(purchase_order_id)
            self._event(
                actor_label=actor_label,
                object_type="ap_purchase_order",
                object_id=purchase_order_id,
                action="ap_purchase_order_approved",
                version=result["row_version"],
                metadata={"from_status": "Submitted", "to_status": "Approved", "actor": actor_label},
            )
            return result

    def get_purchase_order(self, purchase_order_id: str) -> dict[str, Any]:
        with self._transaction():
            return self._purchase_order(purchase_order_id)

    def post_receipt(
        self,
        *,
        receipt_number: str,
        purchase_order_id: str,
        receipt_date: str,
        quantities: dict[str, str],
        workspace: str = "default",
        idempotency_key: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        number = _code(receipt_number, "Receipt number")
        received_on = _iso_date(receipt_date, "Receipt date")
        if not quantities:
            raise PlatformError("Goods receipt quantities are required.")
        if len(quantities) > 1_000:
            raise PlatformError("Goods receipt supports at most 1000 lines.")
        normalized_quantities = {
            _text(line_id, "Purchase-order line id", maximum=128): _quantity(quantity, f"Receipt quantity {line_id}")
            for line_id, quantity in quantities.items()
        }
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            if workspace_id is None:
                raise PostgresPayablesError("Payables workspace was not found for this tenant.")
            previous = self._idempotent("goods_receipt", workspace_id, idempotency_key)
            if previous is not None:
                return previous
            order = self._purchase_order(purchase_order_id)
            if order["workspace_id"] != workspace_id or order["status"] != "Approved":
                raise PlatformError("Goods receipts require an Approved purchase order in the same workspace.")
            line_rows = {str(line["id"]): line for line in order["lines"]}
            for line_id in normalized_quantities:
                if line_id not in line_rows:
                    raise PlatformError(f"Unknown purchase-order line: {line_id}.")
            for line_id, (quantity, _quantity_text) in normalized_quantities.items():
                ordered = Decimal(str(line_rows[line_id]["ordered_quantity"]))
                if self._received_quantity(line_id) + quantity > ordered:
                    raise PlatformError(f"Receipt exceeds ordered quantity for line {line_id}.")
            receipt_id = platform_id("APGR", workspace_id, number)
            row = self.connection.execute(
                """INSERT INTO reconforge.ap_goods_receipts
                   (tenant_id,id,workspace_id,purchase_order_id,receipt_number,receipt_date,
                    status,created_by,posted_by,posted_at)
                   VALUES (%s,%s,%s,%s,%s,%s,'Posted',%s,%s,now())
                   RETURNING id""",
                (
                    self.tenant_id,
                    receipt_id,
                    workspace_id,
                    purchase_order_id,
                    number,
                    received_on,
                    _text(actor_label, "Actor label", maximum=160),
                    _text(actor_label, "Actor label", maximum=160),
                ),
            ).fetchone()
            if row is None:
                raise PostgresPayablesError("Goods receipt was not found after persistence.")
            for line_id, (quantity, quantity_text) in sorted(normalized_quantities.items()):
                self.connection.execute(
                    """INSERT INTO reconforge.ap_goods_receipt_lines
                       (tenant_id,id,receipt_id,purchase_order_line_id,
                        received_quantity,received_quantity_text)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                    (
                        self.tenant_id,
                        platform_id("APGRL", receipt_id, line_id),
                        receipt_id,
                        line_id,
                        quantity,
                        quantity_text,
                    ),
                )
            result = self._receipt(receipt_id)
            self._save_idempotency("goods_receipt", workspace_id, idempotency_key, result)
            self._event(
                actor_label=actor_label,
                object_type="ap_goods_receipt",
                object_id=receipt_id,
                action="ap_goods_receipt_posted",
                metadata={"purchase_order_id": purchase_order_id, "line_count": len(normalized_quantities)},
            )
            return result

    def get_receipt(self, receipt_id: str) -> dict[str, Any]:
        with self._transaction():
            return self._receipt(receipt_id)

    def create_supplier_invoice(
        self,
        *,
        invoice_number: str,
        supplier_code: str,
        invoice_date: str,
        currency_code: str,
        total_minor: int,
        lines: Sequence[SupplierInvoiceLineInput],
        purchase_order_id: str = "",
        tax_minor: int = 0,
        due_date: str = "",
        workspace: str = "default",
        organization_code: str = "",
        entity_code: str = "",
        idempotency_key: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        number = _code(invoice_number, "Supplier invoice number")
        currency = _code(currency_code, "Currency code")
        if len(currency) != 3 or not currency.isalpha():
            raise PlatformError("Currency code must be a three-letter alphabetic code.")
        invoiced_on = _iso_date(invoice_date, "Invoice date")
        due_on = _iso_date(due_date, "Due date", required=False)
        total = _minor(total_minor, "Invoice total")
        tax = _minor(tax_minor, "Invoice tax")
        normalized_lines = _normalize_invoice_lines(lines)
        if sum(line[4] for line in normalized_lines) + tax != total:
            raise PlatformError("Invoice total must equal the sum of line totals plus invoice tax.")
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            if workspace_id is None:
                raise PostgresPayablesError("Payables workspace was not found for this tenant.")
            previous = self._idempotent("supplier_invoice", workspace_id, idempotency_key)
            if previous is not None:
                return previous
            supplier = self._supplier_by_code(workspace_id, supplier_code)
            if supplier["currency_code"] != currency:
                raise PlatformError("Supplier invoice currency must match the supplier currency.")
            organization_id, entity_id = self._scope_ids(
                workspace_id,
                organization_code=organization_code,
                entity_code=entity_code,
            )
            po_id = _text(purchase_order_id, "Purchase order id", maximum=128, required=False)
            po = self._purchase_order(po_id) if po_id else None
            if po is not None and (
                po["workspace_id"] != workspace_id
                or po["supplier_id"] != supplier["id"]
                or po["currency_code"] != currency
            ):
                raise PlatformError("Supplier invoice and purchase order scope, supplier, and currency must match.")
            po_lines = {str(line["id"]): line for line in po["lines"]} if po is not None else {}
            for po_line_id, *_rest in normalized_lines:
                if po is not None and po_line_id not in po_lines:
                    raise PlatformError(f"Invoice line references an unknown purchase-order line: {po_line_id}.")
            invoice_id = platform_id("APINV", workspace_id, supplier["id"], number)
            row = self.connection.execute(
                """INSERT INTO reconforge.ap_supplier_invoices
                   (tenant_id,id,workspace_id,organization_id,legal_entity_id,supplier_id,
                    purchase_order_id,invoice_number,invoice_date,due_date,currency_code,
                    tax_minor,total_minor,status,created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Draft',%s)
                   RETURNING id""",
                (
                    self.tenant_id,
                    invoice_id,
                    workspace_id,
                    organization_id,
                    entity_id,
                    supplier["id"],
                    po_id or None,
                    number,
                    invoiced_on,
                    due_on,
                    currency,
                    tax,
                    total,
                    _text(actor_label, "Actor label", maximum=160),
                ),
            ).fetchone()
            if row is None:
                raise PostgresPayablesError("Supplier invoice was not found after persistence.")
            for line_number, (
                po_line_id,
                quantity,
                quantity_text,
                unit_price,
                line_total,
                description,
                line_tax,
            ) in enumerate(normalized_lines, start=1):
                self.connection.execute(
                    """INSERT INTO reconforge.ap_supplier_invoice_lines
                       (tenant_id,id,supplier_invoice_id,purchase_order_line_id,line_number,
                        description,invoiced_quantity,invoiced_quantity_text,unit_price_minor,
                        tax_minor,line_total_minor)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        self.tenant_id,
                        platform_id("APINVL", invoice_id, line_number, po_line_id),
                        invoice_id,
                        po_line_id or None,
                        line_number,
                        description,
                        quantity,
                        quantity_text,
                        unit_price,
                        line_tax,
                        line_total,
                    ),
                )
            result = self._supplier_invoice(invoice_id)
            self._save_idempotency("supplier_invoice", workspace_id, idempotency_key, result)
            self._event(
                actor_label=actor_label,
                object_type="ap_supplier_invoice",
                object_id=invoice_id,
                action="ap_supplier_invoice_created",
                metadata={"invoice_number": number, "supplier_id": str(supplier["id"]), "total_minor": total},
            )
            return result

    def submit_supplier_invoice(
        self,
        invoice_id: str,
        *,
        expected_version: int,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 1:
            raise PlatformError("Expected version must be a positive integer.")
        with self._transaction():
            row = self.connection.execute(
                """UPDATE reconforge.ap_supplier_invoices
                   SET status='Submitted',updated_at=now(),row_version=row_version+1
                   WHERE tenant_id=%s AND id=%s AND status='Draft' AND row_version=%s
                   RETURNING row_version""",
                (self.tenant_id, _text(invoice_id, "Supplier invoice id", maximum=128), expected_version),
            ).fetchone()
            if row is None:
                raise PlatformError("Supplier invoice changed concurrently or is not ready for submission.")
            result = self._supplier_invoice(invoice_id)
            self._event(
                actor_label=actor_label,
                object_type="ap_supplier_invoice",
                object_id=invoice_id,
                action="ap_supplier_invoice_submitted",
                version=result["row_version"],
                metadata={"from_status": "Draft", "to_status": "Submitted"},
            )
            return result

    def run_three_way_match(self, invoice_id: str, *, actor_label: str = "local-cli") -> ThreeWayMatchResult:
        with self._transaction():
            invoice = self._supplier_invoice(invoice_id)
            po_id = str(invoice["purchase_order_id"] or "")
            po = self._purchase_order(po_id) if po_id else None
            po_lines = {str(line["id"]): line for line in po["lines"]} if po is not None else {}
            quantity_variance = Decimal("0")
            price_variance = Decimal("0")
            total_variance = Decimal("0")
            reasons: list[str] = []
            if po is None:
                reasons.append("AP-3WM-MISSING-PO")
            for line in invoice["lines"]:
                line_id = str(line["purchase_order_line_id"] or "")
                po_line = po_lines.get(line_id)
                if po_line is None:
                    reasons.append(f"AP-3WM-UNKNOWN-LINE:{line_id}")
                    continue
                received = self._received_quantity(line_id)
                invoiced = Decimal(str(line["invoiced_quantity"]))
                quantity_variance += invoiced - received
                unit_price_delta = Decimal(int(line["unit_price_minor"])) - Decimal(int(po_line["unit_price_minor"]))
                price_variance += unit_price_delta * invoiced
                expected_total = _rounded_minor(Decimal(int(po_line["unit_price_minor"])) * invoiced)
                total_variance += Decimal(int(line["line_total_minor"])) - expected_total
                if invoiced > received:
                    reasons.append(f"AP-3WM-QUANTITY:{line_id}")
                if unit_price_delta != 0:
                    reasons.append(f"AP-3WM-PRICE:{line_id}")
            status = (
                "Passed"
                if not reasons and quantity_variance == 0 and price_variance == 0 and total_variance == 0
                else "Exception"
            )
            reason = ";".join(sorted(set(reasons)))
            match_id = platform_id("AP3WM", invoice_id)
            quantity_text = _decimal_text(quantity_variance)
            price_minor = _rounded_minor(price_variance)
            total_variance_minor = _rounded_minor(total_variance)
            self.connection.execute(
                """INSERT INTO reconforge.ap_three_way_matches
                   (tenant_id,id,workspace_id,supplier_invoice_id,purchase_order_id,status,
                    quantity_variance,quantity_variance_text,price_variance_minor,
                    total_variance_minor,reason)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (tenant_id,supplier_invoice_id) DO UPDATE SET
                    purchase_order_id=excluded.purchase_order_id,status=excluded.status,
                    quantity_variance=excluded.quantity_variance,
                    quantity_variance_text=excluded.quantity_variance_text,
                    price_variance_minor=excluded.price_variance_minor,
                    total_variance_minor=excluded.total_variance_minor,
                    reason=excluded.reason,updated_at=now()""",
                (
                    self.tenant_id,
                    match_id,
                    invoice["workspace_id"],
                    invoice_id,
                    po_id or None,
                    status,
                    quantity_variance,
                    quantity_text,
                    price_minor,
                    total_variance_minor,
                    reason,
                ),
            )
            invoice_status = "Matched" if status == "Passed" else "Exception"
            updated = self.connection.execute(
                """UPDATE reconforge.ap_supplier_invoices
                   SET status=%s,updated_at=now(),row_version=row_version+1
                   WHERE tenant_id=%s AND id=%s AND status IN ('Submitted','Matched','Exception')
                   RETURNING row_version""",
                (invoice_status, self.tenant_id, invoice_id),
            ).fetchone()
            if updated is None:
                raise PlatformError("Only a submitted supplier invoice can be matched.")
            exception_id = platform_id("EXC", "ap_three_way_match", match_id)
            if status == "Exception":
                description = f"Supplier invoice three-way match exception: {reason or 'variance'}."
                now = utc_now_text()
                self.connection.execute(
                    """INSERT INTO reconforge.control_exceptions
                       (tenant_id,id,workspace_id,source_type,source_id,period_name,entity_code,
                        account_code,risk_rating,description,status,created_at,updated_at)
                       VALUES (%s,%s,%s,'ap_three_way_match',%s,'',%s,'','high',%s,'Open',%s,%s)
                       ON CONFLICT (tenant_id,source_type,source_id) DO UPDATE SET
                        risk_rating=excluded.risk_rating,description=excluded.description,
                        status='Open',updated_at=excluded.updated_at""",
                    (
                        self.tenant_id,
                        exception_id,
                        invoice["workspace_id"],
                        match_id,
                        str(invoice.get("legal_entity_id") or ""),
                        description,
                        now,
                        now,
                    ),
                )
            else:
                self.connection.execute(
                    """UPDATE reconforge.control_exceptions SET status='Resolved',updated_at=%s
                       WHERE tenant_id=%s AND source_type='ap_three_way_match'
                         AND source_id=%s AND status<>'Resolved'""",
                    (utc_now_text(), self.tenant_id, match_id),
                )
            self._event(
                actor_label=actor_label,
                object_type="ap_three_way_match",
                object_id=match_id,
                action="ap_three_way_match_completed",
                version=status,
                metadata={"invoice_id": invoice_id, "status": status, "reason": reason},
            )
            return ThreeWayMatchResult(
                match_id=match_id,
                invoice_id=invoice_id,
                purchase_order_id=po_id or None,
                status=status,
                quantity_variance=quantity_text,
                price_variance_minor=price_minor,
                total_variance_minor=total_variance_minor,
                reason=reason,
            )

    def approve_supplier_invoice(
        self,
        invoice_id: str,
        *,
        expected_version: int,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 1:
            raise PlatformError("Expected version must be a positive integer.")
        with self._transaction():
            invoice = self._supplier_invoice(invoice_id)
            if invoice["status"] != "Matched":
                raise PlatformError("Only a supplier invoice with a passed three-way match can be approved.")
            if same_actor(invoice.get("created_by"), actor_label):
                raise PlatformError("Separation of duties conflict: invoice creator cannot approve the same invoice.")
            row = self.connection.execute(
                """UPDATE reconforge.ap_supplier_invoices
                   SET status='Approved',approved_by=%s,approved_at=now(),updated_at=now(),row_version=row_version+1
                   WHERE tenant_id=%s AND id=%s AND status='Matched' AND row_version=%s
                   RETURNING row_version""",
                (
                    _text(actor_label, "Actor label", maximum=160),
                    self.tenant_id,
                    invoice_id,
                    expected_version,
                ),
            ).fetchone()
            if row is None:
                raise PlatformError("Supplier invoice changed concurrently or is not ready for approval.")
            result = self._supplier_invoice(invoice_id)
            self._event(
                actor_label=actor_label,
                object_type="ap_supplier_invoice",
                object_id=invoice_id,
                action="ap_supplier_invoice_approved",
                version=result["row_version"],
                metadata={"from_status": "Matched", "to_status": "Approved", "actor": actor_label},
            )
            return result

    def get_supplier_invoice(self, invoice_id: str) -> dict[str, Any]:
        with self._transaction():
            return self._supplier_invoice(invoice_id)

    def list_supplier_invoices(self, *, workspace: str = "default", status: str = "") -> list[dict[str, Any]]:
        normalized_status = _choice(status, "Supplier invoice status", INVOICE_STATUSES) if status.strip() else ""
        with self._transaction():
            workspace_id = self._workspace_id(workspace, required=False)
            if workspace_id is None:
                return []
            rows = self.connection.execute(
                """SELECT id,workspace_id,organization_id,legal_entity_id,supplier_id,purchase_order_id,
                          invoice_number,invoice_date,due_date,currency_code,tax_minor,total_minor,status,
                          created_by,approved_by,approved_at,created_at,updated_at,row_version
                   FROM reconforge.ap_supplier_invoices
                   WHERE tenant_id=%s AND workspace_id=%s AND (%s='' OR status=%s)
                   ORDER BY invoice_date,invoice_number,id""",
                (self.tenant_id, workspace_id, normalized_status, normalized_status),
            ).fetchall()
            return [_row(row, self._INVOICE_COLUMNS) for row in rows]
