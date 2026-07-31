"""PostgreSQL storage contract for governed Accounts Receivable.

The application adapter is added only after its complete thirteen-operation
contract can be exercised.  This schema slice establishes exact, tenant-bound
storage without weakening the local SQLite contract.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from reconforge.application.receivables import ReceiptAllocationInput, ReceivableInvoiceLineInput
from reconforge.auth.rbac import same_actor
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.io.persisted import (
    PersistedJsonError,
    decode_financial_idempotency_response,
    encode_financial_idempotency_response,
    encode_postgres_outbox_payload,
)
from reconforge.platform.common import PlatformError, platform_id

POSTGRES_RECEIVABLES_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.ar_customers (
    tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    organization_id TEXT,
    legal_entity_id TEXT,
    customer_code TEXT NOT NULL,
    name TEXT NOT NULL,
    currency_code TEXT NOT NULL,
    tax_identifier TEXT NOT NULL DEFAULT '',
    payment_terms_days INTEGER NOT NULL DEFAULT 0 CHECK (payment_terms_days >= 0),
    credit_limit_minor BIGINT NOT NULL DEFAULT 0 CHECK (credit_limit_minor >= 0),
    credit_hold BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Draft','Active','Suspended','Closed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    PRIMARY KEY (tenant_id,id),
    UNIQUE (tenant_id,workspace_id,customer_code),
    FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
    FOREIGN KEY (tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
    FOREIGN KEY (tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
    FOREIGN KEY (tenant_id,currency_code) REFERENCES reconforge.currencies(tenant_id,code)
);

CREATE TABLE IF NOT EXISTS reconforge.ar_invoices (
    tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    organization_id TEXT,
    legal_entity_id TEXT,
    customer_id TEXT NOT NULL,
    invoice_number TEXT NOT NULL,
    invoice_date DATE NOT NULL,
    due_date DATE NOT NULL CHECK (due_date >= invoice_date),
    currency_code TEXT NOT NULL,
    subtotal_minor BIGINT NOT NULL CHECK (subtotal_minor >= 0),
    tax_minor BIGINT NOT NULL DEFAULT 0 CHECK (tax_minor >= 0),
    total_minor BIGINT NOT NULL CHECK (total_minor >= 0 AND total_minor = subtotal_minor + tax_minor),
    status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft','Submitted','Approved','PartiallyPaid','Paid','Cancelled')),
    created_by TEXT NOT NULL DEFAULT '',
    approved_by TEXT NOT NULL DEFAULT '',
    approved_at TIMESTAMPTZ,
    credit_override_reason TEXT NOT NULL DEFAULT '',
    cancelled_by TEXT NOT NULL DEFAULT '',
    cancelled_at TIMESTAMPTZ,
    cancel_reason TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    PRIMARY KEY (tenant_id,id),
    UNIQUE (tenant_id,workspace_id,customer_id,invoice_number),
    FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
    FOREIGN KEY (tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
    FOREIGN KEY (tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
    FOREIGN KEY (tenant_id,customer_id) REFERENCES reconforge.ar_customers(tenant_id,id),
    FOREIGN KEY (tenant_id,currency_code) REFERENCES reconforge.currencies(tenant_id,code)
);

CREATE TABLE IF NOT EXISTS reconforge.ar_invoice_lines (
    tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    invoice_id TEXT NOT NULL,
    line_number INTEGER NOT NULL CHECK (line_number > 0),
    description TEXT NOT NULL DEFAULT '',
    quantity NUMERIC NOT NULL CHECK (quantity > 0),
    quantity_text TEXT NOT NULL,
    unit_price_minor BIGINT NOT NULL CHECK (unit_price_minor >= 0),
    tax_minor BIGINT NOT NULL DEFAULT 0 CHECK (tax_minor >= 0),
    line_total_minor BIGINT NOT NULL CHECK (line_total_minor >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id),
    UNIQUE (tenant_id,invoice_id,line_number),
    FOREIGN KEY (tenant_id,invoice_id) REFERENCES reconforge.ar_invoices(tenant_id,id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reconforge.ar_receipts (
    tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    organization_id TEXT,
    legal_entity_id TEXT,
    customer_id TEXT NOT NULL,
    receipt_number TEXT NOT NULL,
    receipt_date DATE NOT NULL,
    currency_code TEXT NOT NULL,
    amount_minor BIGINT NOT NULL CHECK (amount_minor > 0),
    status TEXT NOT NULL DEFAULT 'Posted' CHECK (status IN ('Posted','Cancelled')),
    created_by TEXT NOT NULL DEFAULT '',
    posted_by TEXT NOT NULL DEFAULT '',
    posted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    PRIMARY KEY (tenant_id,id),
    UNIQUE (tenant_id,workspace_id,receipt_number),
    FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
    FOREIGN KEY (tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
    FOREIGN KEY (tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
    FOREIGN KEY (tenant_id,customer_id) REFERENCES reconforge.ar_customers(tenant_id,id),
    FOREIGN KEY (tenant_id,currency_code) REFERENCES reconforge.currencies(tenant_id,code)
);

CREATE TABLE IF NOT EXISTS reconforge.ar_receipt_allocations (
    tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    invoice_id TEXT NOT NULL,
    amount_minor BIGINT NOT NULL CHECK (amount_minor > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id),
    UNIQUE (tenant_id,receipt_id,invoice_id),
    FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
    FOREIGN KEY (tenant_id,receipt_id) REFERENCES reconforge.ar_receipts(tenant_id,id),
    FOREIGN KEY (tenant_id,invoice_id) REFERENCES reconforge.ar_invoices(tenant_id,id)
);

CREATE TABLE IF NOT EXISTS reconforge.ar_idempotency_keys (
    tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    scope TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    response_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,scope,idempotency_key)
);

CREATE INDEX IF NOT EXISTS ar_invoices_customer_status_idx
ON reconforge.ar_invoices(tenant_id,workspace_id,customer_id,status,due_date,invoice_date,id);
CREATE INDEX IF NOT EXISTS ar_receipts_customer_date_idx
ON reconforge.ar_receipts(tenant_id,workspace_id,customer_id,receipt_date,id);
CREATE INDEX IF NOT EXISTS ar_allocations_invoice_idx
ON reconforge.ar_receipt_allocations(tenant_id,workspace_id,invoice_id,created_at,id);

CREATE OR REPLACE FUNCTION reconforge.ar_protect_final_invoice() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status IN ('Approved','PartiallyPaid','Paid','Cancelled') AND
     (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.customer_id,
      NEW.invoice_number,NEW.invoice_date,NEW.due_date,NEW.currency_code,
      NEW.subtotal_minor,NEW.tax_minor,NEW.total_minor,NEW.created_by,NEW.credit_override_reason,NEW.created_at)
     IS DISTINCT FROM
     (OLD.workspace_id,OLD.organization_id,OLD.legal_entity_id,OLD.customer_id,
      OLD.invoice_number,OLD.invoice_date,OLD.due_date,OLD.currency_code,
      OLD.subtotal_minor,OLD.tax_minor,OLD.total_minor,OLD.created_by,OLD.credit_override_reason,OLD.created_at)
  THEN RAISE EXCEPTION 'approved receivable invoices are immutable'; END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS ar_invoice_header_immutable ON reconforge.ar_invoices;
CREATE TRIGGER ar_invoice_header_immutable BEFORE UPDATE ON reconforge.ar_invoices
FOR EACH ROW EXECUTE FUNCTION reconforge.ar_protect_final_invoice();

CREATE OR REPLACE FUNCTION reconforge.ar_protect_final_invoice_line() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM reconforge.ar_invoices i WHERE i.tenant_id=OLD.tenant_id
      AND i.id=OLD.invoice_id AND i.status IN ('Approved','PartiallyPaid','Paid','Cancelled'))
  THEN RAISE EXCEPTION 'approved receivable invoice lines are immutable'; END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS ar_invoice_line_update_blocked ON reconforge.ar_invoice_lines;
CREATE TRIGGER ar_invoice_line_update_blocked BEFORE UPDATE OR DELETE ON reconforge.ar_invoice_lines
FOR EACH ROW EXECUTE FUNCTION reconforge.ar_protect_final_invoice_line();

DO $rls$
DECLARE table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['ar_customers','ar_invoices','ar_invoice_lines','ar_receipts','ar_receipt_allocations','ar_idempotency_keys'] LOOP
    EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I', table_name);
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope') THEN
      EXECUTE format('CREATE POLICY tenant_isolation ON reconforge.%I USING (tenant_id = current_setting(''app.tenant_id'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))', table_name);
    END IF;
  END LOOP;
END $rls$;
"""


CUSTOMER_STATUSES = ("Draft", "Active", "Suspended", "Closed")
INVOICE_STATUSES = ("Draft", "Submitted", "Approved", "PartiallyPaid", "Paid", "Cancelled")


class PostgresReceivablesError(RuntimeError):
    """Safe tenant-scoped Receivables persistence failure."""


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
    result = _text(value, label, maximum=64).upper()
    if not result[0].isalnum() or any(not (character.isalnum() or character in "._-") for character in result):
        raise PlatformError(f"{label} contains unsupported characters.")
    return result


def _currency(value: object) -> str:
    result = _text(value, "Currency code", maximum=3).upper()
    if len(result) != 3 or not result.isalpha() or not result.isascii():
        raise PlatformError("Currency code must be a three-letter alphabetic code.")
    return result


def _minor(value: object, label: str, *, positive: bool = False) -> int:
    if isinstance(value, bool):
        raise PlatformError(f"{label} must be an integer minor-unit value.")
    try:
        result = value if isinstance(value, int) else int(str(value).strip())
    except (TypeError, ValueError, OverflowError) as exc:
        raise PlatformError(f"{label} must be an integer minor-unit value.") from exc
    if result < (1 if positive else 0) or result > 9_000_000_000_000_000_000:
        qualifier = "positive" if positive else "non-negative"
        raise PlatformError(f"{label} must be a supported {qualifier} integer minor-unit value.")
    return result


def _integer(value: object, label: str, *, positive: bool = False) -> int:
    return _minor(value, label, positive=positive)


def _iso_date(value: object, label: str) -> date:
    raw = _text(value, label, maximum=10)
    try:
        result = date.fromisoformat(raw)
    except ValueError as exc:
        raise PlatformError(f"{label} must use YYYY-MM-DD format.") from exc
    if result.isoformat() != raw:
        raise PlatformError(f"{label} must use YYYY-MM-DD format.")
    return result


def _quantity(value: object, label: str) -> tuple[Decimal, str]:
    raw = _text(value, label, maximum=80)
    try:
        result = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise PlatformError(f"{label} must be an exact decimal quantity.") from exc
    if not result.is_finite() or result <= 0:
        raise PlatformError(f"{label} must be finite and positive.")
    normalized = result.normalize()
    return result, format(normalized, "f")


def _row(value: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    if isinstance(value, Mapping):
        result = {column: value[column] for column in columns}
    else:
        result = dict(zip(columns, value, strict=True))
    return {key: item.isoformat() if isinstance(item, date) else item for key, item in result.items()}


def _normalize_lines(lines: Sequence[ReceivableInvoiceLineInput]) -> list[tuple[str, Decimal, str, int, int, int]]:
    if not lines:
        raise PlatformError("Invoice number and at least one line are required.")
    if len(lines) > 1_000:
        raise PlatformError("Receivable invoice supports at most 1000 lines.")
    normalized: list[tuple[str, Decimal, str, int, int, int]] = []
    for number, line in enumerate(lines, start=1):
        quantity, quantity_text = _quantity(line.quantity, f"Invoice line {number} quantity")
        unit_price = _minor(line.unit_price_minor, f"Invoice line {number} unit price")
        line_total = _minor(line.line_total_minor, f"Invoice line {number} total")
        tax = _minor(line.tax_minor, f"Invoice line {number} tax")
        expected = int((quantity * Decimal(unit_price)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if expected != line_total:
            raise PlatformError(f"Invoice line {number} total does not equal quantity multiplied by unit price.")
        normalized.append(
            (
                _text(line.description, f"Invoice line {number} description", maximum=500, required=False),
                quantity,
                quantity_text,
                unit_price,
                tax,
                line_total,
            )
        )
    return normalized


class PostgresReceivablesRepository:
    """Complete tenant-scoped PostgreSQL Receivables application adapter."""

    _CUSTOMER = (
        "id",
        "workspace_id",
        "organization_id",
        "legal_entity_id",
        "customer_code",
        "name",
        "currency_code",
        "tax_identifier",
        "payment_terms_days",
        "credit_limit_minor",
        "credit_hold",
        "status",
        "created_at",
        "updated_at",
        "row_version",
    )
    _INVOICE = (
        "id",
        "workspace_id",
        "organization_id",
        "legal_entity_id",
        "customer_id",
        "invoice_number",
        "invoice_date",
        "due_date",
        "currency_code",
        "subtotal_minor",
        "tax_minor",
        "total_minor",
        "status",
        "created_by",
        "approved_by",
        "approved_at",
        "credit_override_reason",
        "cancelled_by",
        "cancelled_at",
        "cancel_reason",
        "created_at",
        "updated_at",
        "row_version",
    )
    _LINE = (
        "id",
        "invoice_id",
        "line_number",
        "description",
        "quantity",
        "unit_price_minor",
        "tax_minor",
        "line_total_minor",
        "created_at",
    )
    _RECEIPT = (
        "id",
        "workspace_id",
        "organization_id",
        "legal_entity_id",
        "customer_id",
        "receipt_number",
        "receipt_date",
        "currency_code",
        "amount_minor",
        "status",
        "created_by",
        "posted_by",
        "posted_at",
        "created_at",
        "updated_at",
        "row_version",
    )
    _ALLOCATION = ("id", "workspace_id", "receipt_id", "invoice_id", "amount_minor", "created_at")

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, self.tenant_id)
                yield
        except (PlatformError, PostgresReceivablesError):
            raise
        except Exception as exc:
            raise PostgresReceivablesError("PostgreSQL Receivables operation failed.") from exc

    def _workspace_id(self, workspace: str, *, required: bool = True) -> str | None:
        row = self.connection.execute(
            "SELECT id FROM reconforge.domain_workspaces WHERE tenant_id=%s AND name=%s",
            (self.tenant_id, _text(workspace, "Workspace name")),
        ).fetchone()
        if row is None:
            if required:
                raise PostgresReceivablesError("Receivables workspace was not found for this tenant.")
            return None
        return str(row["id"] if isinstance(row, Mapping) else row[0])

    def _required_workspace_id(self, workspace: str) -> str:
        workspace_id = self._workspace_id(workspace)
        if workspace_id is None:
            raise PostgresReceivablesError("Receivables workspace was not found for this tenant.")
        return workspace_id

    def _scope_ids(self, workspace_id: str, organization_code: str, entity_code: str) -> tuple[str | None, str | None]:
        organization_id = None
        legal_entity_id = None
        if organization_code.strip():
            row = self.connection.execute(
                """SELECT o.id FROM reconforge.organizations o JOIN reconforge.master_data_workspace_organizations w ON w.tenant_id=o.tenant_id AND w.organization_id=o.id WHERE o.tenant_id=%s AND w.workspace_id=%s AND o.organization_code=%s AND o.active=TRUE""",
                (self.tenant_id, workspace_id, _code(organization_code, "Organization code")),
            ).fetchone()
            if row is None:
                raise PlatformError("Receivables organization was not found or inactive in this workspace.")
            organization_id = str(row["id"] if isinstance(row, Mapping) else row[0])
        if entity_code.strip():
            if organization_id is None:
                raise PlatformError("Organization is required when a legal entity is supplied.")
            row = self.connection.execute(
                "SELECT id FROM reconforge.legal_entities WHERE tenant_id=%s AND organization_id=%s AND entity_code=%s AND active=TRUE",
                (self.tenant_id, organization_id, _code(entity_code, "Entity code")),
            ).fetchone()
            if row is None:
                raise PlatformError("Receivables legal entity was not found or inactive.")
            legal_entity_id = str(row["id"] if isinstance(row, Mapping) else row[0])
        return organization_id, legal_entity_id

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
            raise PostgresReceivablesError("Receivables event payload is invalid.") from exc
        event_id = platform_id("OBX", action, object_id, version)
        self.connection.execute(
            """INSERT INTO reconforge.outbox_events (tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload) VALUES (%s,%s,%s,%s,%s,CAST(%s AS jsonb)) ON CONFLICT (tenant_id,event_id) DO NOTHING""",
            (self.tenant_id, event_id, action, object_type, object_id, payload),
        )
        PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=actor_label, object_type=object_type, object_id=object_id, action=action, metadata=metadata
        )

    def _customer(self, customer_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT id,workspace_id,organization_id,legal_entity_id,customer_code,name,currency_code,tax_identifier,payment_terms_days,credit_limit_minor,credit_hold,status,created_at,updated_at,row_version FROM reconforge.ar_customers WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, customer_id),
        ).fetchone()
        if row is None:
            raise PlatformError("Customer not found.")
        return _row(row, self._CUSTOMER)

    def _customer_by_code(self, workspace_id: str, customer_code: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT id FROM reconforge.ar_customers WHERE tenant_id=%s AND workspace_id=%s AND customer_code=%s",
            (self.tenant_id, workspace_id, _code(customer_code, "Customer code")),
        ).fetchone()
        if row is None:
            raise PlatformError("Customer not found in the requested workspace.")
        result = self._customer(str(row["id"] if isinstance(row, Mapping) else row[0]))
        if result["status"] != "Active":
            raise PlatformError("Customer is not Active.")
        return result

    def _invoice_allocated(self, invoice_id: str) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(SUM(amount_minor),0) FROM reconforge.ar_receipt_allocations WHERE tenant_id=%s AND invoice_id=%s",
            (self.tenant_id, invoice_id),
        ).fetchone()
        return int((row[0] if not isinstance(row, Mapping) else next(iter(row.values()))) or 0)

    def _invoice(self, invoice_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT id,workspace_id,organization_id,legal_entity_id,customer_id,invoice_number,invoice_date,due_date,currency_code,subtotal_minor,tax_minor,total_minor,status,created_by,approved_by,approved_at,credit_override_reason,cancelled_by,cancelled_at,cancel_reason,created_at,updated_at,row_version FROM reconforge.ar_invoices WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, invoice_id),
        ).fetchone()
        if row is None:
            raise PlatformError("Customer invoice not found.")
        result = _row(row, self._INVOICE)
        lines = self.connection.execute(
            "SELECT id,invoice_id,line_number,description,quantity_text,unit_price_minor,tax_minor,line_total_minor,created_at FROM reconforge.ar_invoice_lines WHERE tenant_id=%s AND invoice_id=%s ORDER BY line_number,id",
            (self.tenant_id, invoice_id),
        ).fetchall()
        result["lines"] = [_row(line, self._LINE) for line in lines]
        result["allocated_minor"] = self._invoice_allocated(invoice_id)
        result["outstanding_minor"] = int(result["total_minor"]) - result["allocated_minor"]
        return result

    def _receipt(self, receipt_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT id,workspace_id,organization_id,legal_entity_id,customer_id,receipt_number,receipt_date,currency_code,amount_minor,status,created_by,posted_by,posted_at,created_at,updated_at,row_version FROM reconforge.ar_receipts WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, receipt_id),
        ).fetchone()
        if row is None:
            raise PlatformError("Customer receipt not found.")
        result = _row(row, self._RECEIPT)
        rows = self.connection.execute(
            "SELECT id,workspace_id,receipt_id,invoice_id,amount_minor,created_at FROM reconforge.ar_receipt_allocations WHERE tenant_id=%s AND receipt_id=%s ORDER BY invoice_id,id",
            (self.tenant_id, receipt_id),
        ).fetchall()
        result["allocations"] = [_row(item, self._ALLOCATION) for item in rows]
        result["allocated_minor"] = sum(int(item["amount_minor"]) for item in result["allocations"])
        result["unallocated_minor"] = int(result["amount_minor"]) - result["allocated_minor"]
        return result

    def _idempotent(self, operation: str, workspace_id: str, key: str) -> dict[str, Any] | None:
        normalized = _text(key, "Idempotency key", maximum=200, required=False)
        if not normalized:
            return None
        row = self.connection.execute(
            "SELECT response_json FROM reconforge.ar_idempotency_keys WHERE tenant_id=%s AND scope=%s AND idempotency_key=%s",
            (self.tenant_id, f"{operation}:{workspace_id}", normalized),
        ).fetchone()
        if row is None:
            return None
        raw = row["response_json"] if isinstance(row, Mapping) else row[0]
        try:
            return decode_financial_idempotency_response(raw).payload
        except PersistedJsonError as exc:
            raise PostgresReceivablesError("Stored Receivables idempotency response is invalid.") from exc

    def _save_idempotency(self, operation: str, workspace_id: str, key: str, result: dict[str, Any]) -> None:
        normalized = _text(key, "Idempotency key", maximum=200, required=False)
        if not normalized:
            return
        try:
            document = encode_financial_idempotency_response(result)
        except PersistedJsonError as exc:
            raise PostgresReceivablesError("Receivables idempotency response is invalid.") from exc
        self.connection.execute(
            "INSERT INTO reconforge.ar_idempotency_keys(tenant_id,scope,idempotency_key,response_json) VALUES (%s,%s,%s,CAST(%s AS jsonb))",
            (self.tenant_id, f"{operation}:{workspace_id}", normalized, document.text),
        )

    def upsert_customer(
        self,
        *,
        customer_code: str,
        name: str,
        currency_code: str,
        credit_limit_minor: int,
        credit_hold: bool = False,
        payment_terms_days: int = 0,
        workspace: str = "default",
        organization_code: str = "",
        entity_code: str = "",
        tax_identifier: str = "",
        status: str = "Active",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        code, currency = _code(customer_code, "Customer code"), _currency(currency_code)
        customer_status = next((item for item in CUSTOMER_STATUSES if item.lower() == status.strip().lower()), None)
        if customer_status is None:
            raise PlatformError("Invalid customer status.")
        with self._transaction():
            workspace_id = self._required_workspace_id(workspace)
            organization_id, entity_id = self._scope_ids(workspace_id, organization_code, entity_code)
            customer_id = platform_id("ARCUS", workspace_id, code)
            self.connection.execute(
                """INSERT INTO reconforge.ar_customers(tenant_id,id,workspace_id,organization_id,legal_entity_id,customer_code,name,currency_code,tax_identifier,payment_terms_days,credit_limit_minor,credit_hold,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,workspace_id,customer_code) DO UPDATE SET organization_id=excluded.organization_id,legal_entity_id=excluded.legal_entity_id,name=excluded.name,currency_code=excluded.currency_code,tax_identifier=excluded.tax_identifier,payment_terms_days=excluded.payment_terms_days,credit_limit_minor=excluded.credit_limit_minor,credit_hold=excluded.credit_hold,status=excluded.status,updated_at=now(),row_version=ar_customers.row_version+1""",
                (
                    self.tenant_id,
                    customer_id,
                    workspace_id,
                    organization_id,
                    entity_id,
                    code,
                    _text(name, "Customer name"),
                    currency,
                    _text(tax_identifier, "Tax identifier", maximum=100, required=False),
                    _integer(payment_terms_days, "Payment terms"),
                    _minor(credit_limit_minor, "Credit limit"),
                    bool(credit_hold),
                    customer_status,
                ),
            )
            result = self._customer(customer_id)
            self._event(
                actor_label=actor_label,
                object_type="ar_customer",
                object_id=customer_id,
                action="ar_customer_saved",
                version=result["row_version"],
                metadata={"customer_code": code, "status": customer_status},
            )
            return result

    def create_invoice(
        self,
        *,
        invoice_number: str,
        customer_code: str,
        invoice_date: str,
        currency_code: str,
        tax_minor: int,
        lines: Sequence[ReceivableInvoiceLineInput],
        due_date: str = "",
        workspace: str = "default",
        organization_code: str = "",
        entity_code: str = "",
        idempotency_key: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        number, day, currency = (
            _code(invoice_number, "Invoice number"),
            _iso_date(invoice_date, "Invoice date"),
            _currency(currency_code),
        )
        normalized = _normalize_lines(lines)
        tax = _minor(tax_minor, "Invoice tax")
        if sum(line[4] for line in normalized) != tax:
            raise PlatformError("Invoice tax must equal the sum of invoice-line tax amounts.")
        with self._transaction():
            workspace_id = self._required_workspace_id(workspace)
            previous = self._idempotent("invoice", workspace_id, idempotency_key)
            if previous is not None:
                return previous
            customer = self._customer_by_code(workspace_id, customer_code)
            if customer["currency_code"] != currency:
                raise PlatformError("Customer invoice currency must match the customer currency.")
            due = (
                _iso_date(due_date, "Due date")
                if due_date.strip()
                else day + timedelta(days=int(customer["payment_terms_days"]))
            )
            if due < day:
                raise PlatformError("Due date cannot be before invoice date.")
            organization_id, entity_id = self._scope_ids(workspace_id, organization_code, entity_code)
            subtotal = sum(line[5] for line in normalized)
            invoice_id = platform_id("ARINV", workspace_id, customer["id"], number)
            self.connection.execute(
                """INSERT INTO reconforge.ar_invoices(tenant_id,id,workspace_id,organization_id,legal_entity_id,customer_id,invoice_number,invoice_date,due_date,currency_code,subtotal_minor,tax_minor,total_minor,status,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Draft',%s)""",
                (
                    self.tenant_id,
                    invoice_id,
                    workspace_id,
                    organization_id,
                    entity_id,
                    customer["id"],
                    number,
                    day,
                    due,
                    currency,
                    subtotal,
                    tax,
                    subtotal + tax,
                    _text(actor_label, "Actor label"),
                ),
            )
            for line_number, line in enumerate(normalized, start=1):
                self.connection.execute(
                    "INSERT INTO reconforge.ar_invoice_lines(tenant_id,id,invoice_id,line_number,description,quantity,quantity_text,unit_price_minor,tax_minor,line_total_minor) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (self.tenant_id, platform_id("ARINVL", invoice_id, line_number), invoice_id, line_number, *line),
                )
            result = self._invoice(invoice_id)
            self._save_idempotency("invoice", workspace_id, idempotency_key, result)
            self._event(
                actor_label=actor_label,
                object_type="ar_invoice",
                object_id=invoice_id,
                action="ar_invoice_created",
                version="created",
                metadata={"customer_id": customer["id"], "total_minor": subtotal + tax},
            )
            return result

    def submit_invoice(
        self, invoice_id: str, *, expected_version: int, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        return self._transition(invoice_id, "Draft", "Submitted", expected_version, actor_label, "ar_invoice_submitted")

    def _transition(
        self, invoice_id: str, source: str, target: str, expected_version: int, actor_label: str, action: str
    ) -> dict[str, Any]:
        if isinstance(expected_version, bool) or expected_version < 1:
            raise PlatformError("Expected row version must be positive.")
        with self._transaction():
            row = self.connection.execute(
                "UPDATE reconforge.ar_invoices SET status=%s,updated_at=now(),row_version=row_version+1 WHERE tenant_id=%s AND id=%s AND status=%s AND row_version=%s RETURNING row_version",
                (target, self.tenant_id, invoice_id, source, expected_version),
            ).fetchone()
            if row is None:
                raise PlatformError("Invoice changed concurrently or is not in the expected lifecycle state.")
            result = self._invoice(invoice_id)
            self._event(
                actor_label=actor_label,
                object_type="ar_invoice",
                object_id=invoice_id,
                action=action,
                version=result["row_version"],
                metadata={"from_status": source, "to_status": target},
            )
            return result

    def _exposure(self, customer_id: str, exclude_invoice_id: str = "") -> int:
        row = self.connection.execute(
            """SELECT COALESCE(SUM(i.total_minor),0)-COALESCE(SUM(a.allocated),0) FROM reconforge.ar_invoices i LEFT JOIN (SELECT tenant_id,invoice_id,SUM(amount_minor) allocated FROM reconforge.ar_receipt_allocations GROUP BY tenant_id,invoice_id) a ON a.tenant_id=i.tenant_id AND a.invoice_id=i.id WHERE i.tenant_id=%s AND i.customer_id=%s AND i.status IN ('Approved','PartiallyPaid') AND i.id<>%s""",
            (self.tenant_id, customer_id, exclude_invoice_id),
        ).fetchone()
        value = row[0] if not isinstance(row, Mapping) else next(iter(row.values()))
        return max(int(value or 0), 0)

    def approve_invoice(
        self,
        invoice_id: str,
        *,
        expected_version: int,
        credit_override_reason: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        with self._transaction():
            invoice = self._invoice(invoice_id)
            if invoice["status"] != "Submitted":
                raise PlatformError("Only a submitted receivable invoice can be approved.")
            if same_actor(invoice.get("created_by"), actor_label):
                raise PlatformError("Separation of duties conflict: invoice creator cannot approve the same invoice.")
            self.connection.execute(
                "SELECT id FROM reconforge.ar_customers WHERE tenant_id=%s AND id=%s FOR UPDATE",
                (self.tenant_id, invoice["customer_id"]),
            )
            customer = self._customer(str(invoice["customer_id"]))
            exposure = self._exposure(str(customer["id"]), invoice_id)
            override = _text(credit_override_reason, "Credit override reason", maximum=500, required=False)
            if (
                bool(customer["credit_hold"])
                or exposure + int(invoice["total_minor"]) > int(customer["credit_limit_minor"])
            ) and not override:
                raise PlatformError("Credit control blocked invoice approval: hold or credit limit breach.")
            row = self.connection.execute(
                "UPDATE reconforge.ar_invoices SET status='Approved',approved_by=%s,approved_at=now(),credit_override_reason=%s,updated_at=now(),row_version=row_version+1 WHERE tenant_id=%s AND id=%s AND status='Submitted' AND row_version=%s RETURNING row_version",
                (_text(actor_label, "Actor label"), override, self.tenant_id, invoice_id, expected_version),
            ).fetchone()
            if row is None:
                raise PlatformError("Invoice changed concurrently or is not ready for approval.")
            result = self._invoice(invoice_id)
            self._event(
                actor_label=actor_label,
                object_type="ar_invoice",
                object_id=invoice_id,
                action="ar_invoice_approved",
                version=result["row_version"],
                metadata={"exposure_before_minor": exposure, "credit_override": bool(override)},
            )
            return result

    def _allocate(self, receipt: dict[str, Any], invoice_id: str, amount: int) -> None:
        self.connection.execute(
            "SELECT id FROM reconforge.ar_receipts WHERE tenant_id=%s AND id=%s FOR UPDATE",
            (self.tenant_id, receipt["id"]),
        )
        self.connection.execute(
            "SELECT id FROM reconforge.ar_invoices WHERE tenant_id=%s AND id=%s FOR UPDATE",
            (self.tenant_id, invoice_id),
        )
        receipt = self._receipt(str(receipt["id"]))
        invoice = self._invoice(invoice_id)
        if (
            invoice["workspace_id"] != receipt["workspace_id"]
            or invoice["customer_id"] != receipt["customer_id"]
            or invoice["currency_code"] != receipt["currency_code"]
        ):
            raise PlatformError("Receipt allocation scope, customer, and currency must match the invoice.")
        if invoice["status"] not in {"Approved", "PartiallyPaid"} or int(invoice["outstanding_minor"]) < amount:
            raise PlatformError("Allocation requires an open approved invoice and cannot exceed its balance.")
        if int(receipt["allocated_minor"]) + amount > int(receipt["amount_minor"]):
            raise PlatformError("Receipt allocations cannot exceed the receipt amount.")
        allocation_id = platform_id("ARALLOC", receipt["id"], invoice_id)
        self.connection.execute(
            """INSERT INTO reconforge.ar_receipt_allocations(tenant_id,id,workspace_id,receipt_id,invoice_id,amount_minor) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,receipt_id,invoice_id) DO UPDATE SET amount_minor=ar_receipt_allocations.amount_minor+excluded.amount_minor""",
            (self.tenant_id, allocation_id, receipt["workspace_id"], receipt["id"], invoice_id, amount),
        )
        allocated = self._invoice_allocated(invoice_id)
        status = "Paid" if allocated >= int(invoice["total_minor"]) else "PartiallyPaid"
        self.connection.execute(
            "UPDATE reconforge.ar_invoices SET status=%s,updated_at=now(),row_version=row_version+1 WHERE tenant_id=%s AND id=%s",
            (status, self.tenant_id, invoice_id),
        )

    def post_receipt(
        self,
        *,
        receipt_number: str,
        customer_code: str,
        receipt_date: str,
        currency_code: str,
        amount_minor: int,
        allocations: Sequence[ReceiptAllocationInput] = (),
        workspace: str = "default",
        organization_code: str = "",
        entity_code: str = "",
        idempotency_key: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        number, day, currency, amount = (
            _code(receipt_number, "Receipt number"),
            _iso_date(receipt_date, "Receipt date"),
            _currency(currency_code),
            _minor(amount_minor, "Receipt amount", positive=True),
        )
        normalized = [
            (
                _text(item.invoice_id, "Invoice id", maximum=128),
                _minor(item.amount_minor, "Allocation amount", positive=True),
            )
            for item in allocations
        ]
        if len({item[0] for item in normalized}) != len(normalized):
            raise PlatformError("Receipt allocations must contain each invoice at most once.")
        with self._transaction():
            workspace_id = self._required_workspace_id(workspace)
            previous = self._idempotent("receipt", workspace_id, idempotency_key)
            if previous is not None:
                return previous
            customer = self._customer_by_code(workspace_id, customer_code)
            if customer["currency_code"] != currency:
                raise PlatformError("Customer receipt currency must match the customer currency.")
            organization_id, entity_id = self._scope_ids(workspace_id, organization_code, entity_code)
            receipt_id = platform_id("ARRCT", workspace_id, number)
            self.connection.execute(
                "INSERT INTO reconforge.ar_receipts(tenant_id,id,workspace_id,organization_id,legal_entity_id,customer_id,receipt_number,receipt_date,currency_code,amount_minor,status,created_by,posted_by,posted_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Posted',%s,%s,now())",
                (
                    self.tenant_id,
                    receipt_id,
                    workspace_id,
                    organization_id,
                    entity_id,
                    customer["id"],
                    number,
                    day,
                    currency,
                    amount,
                    _text(actor_label, "Actor label"),
                    _text(actor_label, "Actor label"),
                ),
            )
            receipt = self._receipt(receipt_id)
            for invoice_id, allocation_amount in normalized:
                self._allocate(receipt, invoice_id, allocation_amount)
                receipt["allocated_minor"] = int(receipt["allocated_minor"]) + allocation_amount
            result = self._receipt(receipt_id)
            self._save_idempotency("receipt", workspace_id, idempotency_key, result)
            self._event(
                actor_label=actor_label,
                object_type="ar_receipt",
                object_id=receipt_id,
                action="ar_receipt_posted",
                version="posted",
                metadata={"customer_id": customer["id"], "amount_minor": amount},
            )
            return result

    def allocate_receipt(
        self,
        receipt_id: str,
        *,
        invoice_id: str,
        amount_minor: int,
        expected_version: int,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        amount = _minor(amount_minor, "Allocation amount", positive=True)
        with self._transaction():
            receipt = self._receipt(receipt_id)
            if receipt["status"] != "Posted" or int(receipt["row_version"]) != expected_version:
                raise PlatformError("Receipt changed concurrently or is not Posted.")
            self._allocate(receipt, invoice_id, amount)
            row = self.connection.execute(
                "UPDATE reconforge.ar_receipts SET updated_at=now(),row_version=row_version+1 WHERE tenant_id=%s AND id=%s AND row_version=%s RETURNING row_version",
                (self.tenant_id, receipt_id, expected_version),
            ).fetchone()
            if row is None:
                raise PlatformError("Receipt changed concurrently.")
            result = self._receipt(receipt_id)
            self._event(
                actor_label=actor_label,
                object_type="ar_receipt",
                object_id=receipt_id,
                action="ar_receipt_allocated",
                version=result["row_version"],
                metadata={"invoice_id": invoice_id, "amount_minor": amount},
            )
            return result

    def get_customer(self, customer_id: str) -> dict[str, Any]:
        with self._transaction():
            return self._customer(customer_id)

    def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        with self._transaction():
            return self._invoice(invoice_id)

    def get_receipt(self, receipt_id: str) -> dict[str, Any]:
        with self._transaction():
            return self._receipt(receipt_id)

    def list_customers(self, *, workspace: str = "", status: str = "") -> list[dict[str, Any]]:
        with self._transaction():
            workspace_id = self._workspace_id(workspace or "default", required=False)
            if workspace_id is None:
                return []
            rows = self.connection.execute(
                "SELECT id FROM reconforge.ar_customers WHERE tenant_id=%s AND workspace_id=%s AND (%s='' OR status=%s) ORDER BY customer_code,id",
                (self.tenant_id, workspace_id, status, status),
            ).fetchall()
            return [self._customer(str(row["id"] if isinstance(row, Mapping) else row[0])) for row in rows]

    def list_invoices(self, *, workspace: str = "default", status: str = "") -> list[dict[str, Any]]:
        with self._transaction():
            workspace_id = self._workspace_id(workspace, required=False)
            if workspace_id is None:
                return []
            rows = self.connection.execute(
                "SELECT id FROM reconforge.ar_invoices WHERE tenant_id=%s AND workspace_id=%s AND (%s='' OR status=%s) ORDER BY invoice_date,invoice_number,id",
                (self.tenant_id, workspace_id, status, status),
            ).fetchall()
            return [self._invoice(str(row["id"] if isinstance(row, Mapping) else row[0])) for row in rows]

    def credit_exposure(self, customer_code: str, *, workspace: str = "default") -> dict[str, Any]:
        with self._transaction():
            workspace_id = self._required_workspace_id(workspace)
            customer = self._customer_by_code(workspace_id, customer_code)
            exposure = self._exposure(str(customer["id"]))
            limit = int(customer["credit_limit_minor"])
            return {
                "customer_id": customer["id"],
                "customer_code": customer["customer_code"],
                "currency_code": customer["currency_code"],
                "credit_limit_minor": limit,
                "exposure_minor": exposure,
                "available_credit_minor": limit - exposure,
                "credit_hold": bool(customer["credit_hold"]),
                "status": customer["status"],
            }

    def aging_report(self, *, workspace: str = "default", as_of_date: str) -> dict[str, Any]:
        as_of = _iso_date(as_of_date, "Aging as-of date")
        with self._transaction():
            workspace_id = self._required_workspace_id(workspace)
            rows = self.connection.execute(
                """SELECT i.id,i.invoice_number,c.customer_code,c.name,i.currency_code,i.invoice_date,i.due_date,i.total_minor FROM reconforge.ar_invoices i JOIN reconforge.ar_customers c ON c.tenant_id=i.tenant_id AND c.id=i.customer_id WHERE i.tenant_id=%s AND i.workspace_id=%s AND i.status IN ('Approved','PartiallyPaid') ORDER BY i.due_date,i.invoice_number,i.id""",
                (self.tenant_id, workspace_id),
            ).fetchall()
            columns = (
                "id",
                "invoice_number",
                "customer_code",
                "customer_name",
                "currency_code",
                "invoice_date",
                "due_date",
                "total_minor",
            )
            buckets = {"Current": 0, "1-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
            items = []
            for raw in rows:
                row = _row(raw, columns)
                outstanding = int(row["total_minor"]) - self._invoice_allocated(str(row["id"]))
                if outstanding <= 0:
                    continue
                due = date.fromisoformat(str(row["due_date"]))
                days = max((as_of - due).days, 0)
                bucket = (
                    "Current"
                    if days == 0
                    else "1-30"
                    if days <= 30
                    else "31-60"
                    if days <= 60
                    else "61-90"
                    if days <= 90
                    else "90+"
                )
                buckets[bucket] += outstanding
                items.append(
                    {
                        "invoice_id": row["id"],
                        "invoice_number": row["invoice_number"],
                        "customer_code": row["customer_code"],
                        "customer_name": row["customer_name"],
                        "currency_code": row["currency_code"],
                        "invoice_date": row["invoice_date"],
                        "due_date": row["due_date"],
                        "total_minor": row["total_minor"],
                        "outstanding_minor": outstanding,
                        "days_overdue": days,
                        "bucket": bucket,
                    }
                )
            return {
                "as_of_date": as_of.isoformat(),
                "items": items,
                "bucket_totals_minor": buckets,
                "total_outstanding_minor": sum(buckets.values()),
            }
