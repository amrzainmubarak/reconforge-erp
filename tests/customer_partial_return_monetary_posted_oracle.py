"""Strict raw contract for the new monetary original/posted-cycle evidence.

This first layer preserves all 91 tables and exact PostgreSQL row texts. Passing
it establishes a bounded, tenant-bound input contract, not source ownership,
journal correctness, current authority, a posted cycle or native acceptance.
The independent arithmetic reference and later native row joins remain separate
from this decoder. No production code or older financial reader is imported.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, cast

TABLES = (
    "ar_customers", "ar_idempotency_keys", "ar_invoice_lines", "ar_invoices",
    "ar_receipt_allocations", "ar_receipts", "commercial_collection_cancellations",
    "commercial_collection_commands", "commercial_collection_links", "commercial_collection_plans",
    "commercial_collection_reviews", "customer_partial_return_allocation_witnesses",
    "customer_partial_return_commands", "customer_partial_return_events", "customer_partial_return_history",
    "customer_partial_return_monetary_commands", "customer_partial_return_monetary_entries",
    "customer_partial_return_monetary_events", "customer_partial_return_monetary_history",
    "customer_partial_return_monetary_plans", "customer_partial_return_monetary_restorations",
    "customer_partial_return_plans", "customer_partial_return_restorations", "customer_partial_return_sources",
    "customer_return_commands", "customer_return_events", "customer_return_plans",
    "domain_audit_events", "domain_audit_ledger_state", "finance_accounts", "finance_charts",
    "finance_dimension_values", "finance_dimensions", "finance_entries", "finance_entry_line_dimensions",
    "finance_entry_lines", "finance_journals", "finance_posting_commands", "finance_posting_effects",
    "inventory_cost_layers", "inventory_count_lines", "inventory_count_sessions", "inventory_items",
    "inventory_layer_consumptions", "inventory_locations", "inventory_lots", "inventory_movement_lines",
    "inventory_movements", "inventory_quantity_claim_gates", "inventory_quantity_source_guards",
    "inventory_quantity_source_releases", "inventory_receipt_commands", "inventory_receipt_links",
    "inventory_receipt_plans", "inventory_receipt_reviews", "inventory_reorder_rules",
    "inventory_transfer_claims", "inventory_transfer_commands", "inventory_transfer_events",
    "inventory_transfer_releases", "inventory_transfer_sources", "inventory_units_of_measure",
    "inventory_valuation_documents", "inventory_valuation_input_costs", "inventory_valuation_lines",
    "inventory_valuation_policies", "inventory_valuation_reversal_effects", "inventory_valuation_reversals",
    "inventory_warehouses", "operational_finance_commands", "operational_finance_links",
    "operational_finance_plans", "operational_finance_reviews", "operational_fx_commands",
    "operational_fx_links", "operational_fx_plans", "operational_fx_reviews", "operational_fx_sources",
    "outbox_consumer_receipts", "outbox_delivery_evidence", "outbox_events", "stock_commerce_commands",
    "stock_commerce_lines", "stock_commerce_orders", "stock_commerce_tranches", "stock_sales_commands",
    "stock_sales_events", "stock_sales_issue_claims", "stock_sales_monetary_origins",
    "stock_sales_orders", "stock_sales_reservations",
)
SCHEMA = "customer-partial-return-monetary-posted-cycle-input-v1"
MAX_PACKET_BYTES = 64 * 1024 * 1024
MAX_CAPTURE_BYTES = 4 * 1024 * 1024
MAX_ROW_BYTES = 256 * 1024
MAX_CAPTURE_ROWS = 20_000
MAX_MINOR = 9_000_000_000_000_000_000
MAX_CAPTURES = 257  # Original plus at most 256 ordered monetary events.


class MonetaryRawRefusal(ValueError):
    """A constant error never contains a private original row or identifier."""


def require(condition: bool) -> None:
    if not condition:
        raise MonetaryRawRefusal("Independent monetary raw input refused.")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def _int(token: str) -> int:
    require(len(token) <= 20)
    value = int(token)
    require(-MAX_MINOR <= value <= MAX_MINOR)
    return value


def _fraction(token: str) -> Fraction:
    # PG jsonb emits ordinary exact decimal numbers; no expanded exponent input.
    require(len(token) <= 96 and re.fullmatch(r"-?(?:0|[1-9][0-9]*)\.[0-9]+", token) is not None)
    return Fraction(token)


def _constant(_token: str) -> Any:
    raise MonetaryRawRefusal("Independent monetary raw input refused.")


def _decode(value: str | bytes) -> Any:
    try:
        return json.loads(value, object_pairs_hook=_object, parse_int=_int,
                          parse_float=_fraction, parse_constant=_constant)
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise MonetaryRawRefusal("Independent monetary raw input refused.") from exc


def _identity(value: object) -> str:
    require(type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", value) is not None)
    return cast(str, value)


def _raw_row(value: object, tenant_id: str) -> dict[str, Any]:
    require(type(value) is str)
    text = cast(str, value)
    try:
        require(len(text.encode("utf-8")) <= MAX_ROW_BYTES)
    except UnicodeError:
        raise MonetaryRawRefusal("Independent monetary raw input refused.") from None
    row = _decode(text)
    require(type(row) is dict and row.get("tenant_id") == tenant_id)
    return row


@dataclass(frozen=True)
class Capture:
    index: int
    raw_tables: tuple[tuple[str, tuple[str, ...]], ...]
    sha256: str

    def rows(self, table: str) -> tuple[dict[str, Any], ...]:
        require(type(table) is str and table in TABLES)
        return tuple(_decode(row) for name, rows in self.raw_tables if name == table for row in rows)


@dataclass(frozen=True)
class RawPacket:
    tenant_id: str
    source_order_id: str
    captures: tuple[Capture, ...]
    sha256: str
    byte_size: int


def decode_capture(value: object, *, index: int, tenant_id: str) -> Capture:
    """Validate one exact {capture,tables} envelope, preserving every SQL text."""
    _identity(tenant_id)
    require(type(index) is int and 0 <= index < MAX_CAPTURES)
    require(type(value) is dict and set(value) == {"capture", "tables"})
    envelope = cast(dict[str, Any], value)
    require(type(envelope["capture"]) is int and envelope["capture"] == index)
    tables = envelope["tables"]
    require(type(tables) is dict and set(tables) == set(TABLES))
    original, byte_size, row_count = [], 0, 0
    for name in TABLES:
        rows = tables[name]
        require(type(rows) is list and all(type(row) is str for row in rows))
        require(rows == sorted(rows) and len(rows) == len(set(rows)))
        row_count += len(rows)
        require(row_count <= MAX_CAPTURE_ROWS)
        for row in rows:
            _raw_row(row, tenant_id)
            byte_size += len(row.encode("utf-8"))
            require(byte_size <= MAX_CAPTURE_BYTES)
        original.append((name, tuple(rows)))
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    require(len(canonical) <= MAX_CAPTURE_BYTES)
    return Capture(index, tuple(original), hashlib.sha256(canonical).hexdigest())


def decode_packet(original: bytes) -> RawPacket:
    """Decode the input contract only; no successful financial proof is emitted."""
    require(type(original) is bytes and 0 < len(original) <= MAX_PACKET_BYTES)
    value = _decode(original)
    require(type(value) is dict and set(value) == {"schema_version", "tenant_id", "source_order_id", "captures"})
    require(value["schema_version"] == SCHEMA)
    tenant, order = _identity(value["tenant_id"]), _identity(value["source_order_id"])
    values = value["captures"]
    require(type(values) is list and 2 <= len(values) <= MAX_CAPTURES)
    captures = tuple(decode_capture(capture, index=index, tenant_id=tenant) for index, capture in enumerate(values))
    return RawPacket(tenant, order, captures, hashlib.sha256(original).hexdigest(), len(original))


def _stable(value: Any) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _regular(path: Path) -> Any:
    require(path.is_absolute() and ".." not in path.parts)
    try:
        for candidate in (*reversed(path.parents), path):
            info = candidate.lstat()
            require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400)
            require(stat.S_ISREG(info.st_mode) if candidate == path else stat.S_ISDIR(info.st_mode))
        require(info.st_size <= MAX_PACKET_BYTES)
        return info
    except OSError as exc:
        raise MonetaryRawRefusal("Independent monetary raw input refused.") from exc


def read_original(path: Path) -> bytes:
    """Bound one regular original read and compare stable identity, never atime."""
    try:
        before = _regular(path)
        with path.open("rb") as stream:
            require(_stable(os.fstat(stream.fileno())) == _stable(before))
            original = stream.read(MAX_PACKET_BYTES + 1)
        require(len(original) == before.st_size and len(original) <= MAX_PACKET_BYTES)
        require(_stable(_regular(path)) == _stable(before))
        return original
    except OSError as exc:
        raise MonetaryRawRefusal("Independent monetary raw input refused.") from exc


def require_original_unchanged(path: Path, original: bytes) -> None:
    """A second bounded byte comparison is required after future row joins."""
    require(type(original) is bytes and read_original(path) == original)
