"""Input schema definitions and canonical dataset names."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class DatasetName(str, Enum):
    """Supported ERP extract names."""

    STOCK_MOVES = "stock_moves"
    GL_ENTRIES = "gl_entries"
    WORK_ORDERS = "work_orders"
    PURCHASE_ORDERS = "purchase_orders"
    PRODUCTS = "products"
    CUSTOMERS = "customers"
    OLD_PARTS_RETURNS = "old_parts_returns"
    INVOICES = "invoices"


REQUIRED_COLUMNS: dict[DatasetName, list[str]] = {
    DatasetName.STOCK_MOVES: [
        "move_id",
        "date",
        "source_document",
        "work_order",
        "product_code",
        "product_name",
        "category",
        "quantity",
        "unit_cost",
        "total_cost",
        "warehouse",
        "movement_type",
        "customer_code",
        "equipment_serial",
        "created_by",
    ],
    DatasetName.GL_ENTRIES: [
        "entry_id",
        "date",
        "journal",
        "account_code",
        "account_name",
        "reference",
        "source_document",
        "debit",
        "credit",
        "amount",
        "cost_center",
        "work_order",
        "created_by",
    ],
    DatasetName.WORK_ORDERS: [
        "work_order",
        "customer_code",
        "customer_name",
        "equipment_serial",
        "status",
        "opened_date",
        "closed_date",
        "service_type",
        "responsible_engineer",
        "workshop",
        "estimated_cost",
        "actual_cost",
    ],
    DatasetName.PURCHASE_ORDERS: [
        "po_number",
        "supplier_code",
        "supplier_name",
        "po_date",
        "product_code",
        "quantity",
        "unit_price",
        "total_price",
        "status",
        "linked_work_order",
    ],
    DatasetName.PRODUCTS: [
        "product_code",
        "product_name",
        "category",
        "standard_cost",
        "stock_account",
        "expense_account",
    ],
    DatasetName.CUSTOMERS: [
        "customer_code",
        "customer_name",
        "segment",
        "region",
    ],
    DatasetName.OLD_PARTS_RETURNS: [
        "return_id",
        "work_order",
        "product_code",
        "returned_quantity",
        "return_date",
        "received_by",
        "condition",
    ],
    DatasetName.INVOICES: [
        "invoice_number",
        "work_order",
        "customer_code",
        "invoice_date",
        "invoice_amount",
        "status",
    ],
}


DATE_COLUMNS: dict[DatasetName, list[str]] = {
    DatasetName.STOCK_MOVES: ["date"],
    DatasetName.GL_ENTRIES: ["date"],
    DatasetName.WORK_ORDERS: ["opened_date", "closed_date"],
    DatasetName.PURCHASE_ORDERS: ["po_date"],
    DatasetName.OLD_PARTS_RETURNS: ["return_date"],
    DatasetName.INVOICES: ["invoice_date"],
    DatasetName.PRODUCTS: [],
    DatasetName.CUSTOMERS: [],
}


NUMERIC_COLUMNS: dict[DatasetName, list[str]] = {
    DatasetName.STOCK_MOVES: ["quantity", "unit_cost", "total_cost"],
    DatasetName.GL_ENTRIES: ["debit", "credit", "amount"],
    DatasetName.WORK_ORDERS: ["estimated_cost", "actual_cost"],
    DatasetName.PURCHASE_ORDERS: ["quantity", "unit_price", "total_price"],
    DatasetName.PRODUCTS: ["standard_cost"],
    DatasetName.OLD_PARTS_RETURNS: ["returned_quantity"],
    DatasetName.INVOICES: ["invoice_amount"],
    DatasetName.CUSTOMERS: [],
}


class ValidationIssue(BaseModel):
    """A structured validation issue."""

    dataset: str
    severity: str
    check: str
    message: str
    row: int | None = None
    column: str | None = None
    reference: str | None = None


class ReportArtifact(BaseModel):
    """A generated report artifact."""

    name: str
    path: str
    format: str
