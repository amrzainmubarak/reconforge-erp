"""Strict raw contract for the new monetary original/posted-cycle evidence.

The decoder preserves all 91 tables and exact PostgreSQL row texts. Separate
stages join original Stock/AR/FX/FIFO facts and independently derive history,
posted journals and physical corrections. The decoder alone establishes only a
bounded input contract. No complete-cycle/native acceptance marker is emitted;
actual source custody, chronology, observations and restore remain required.
No production code or older financial reader is imported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import date, datetime
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
_COMMON = "tenant_id workspace_id organization_id legal_entity_id "
MONETARY_COLUMNS = {
    "stock_sales_monetary_origins": frozenset((_COMMON + "id stock_order_id invoice_id fx_source_id recognition_plan_id payload source_digest ar_balance").split()),
    "customer_partial_return_monetary_plans": frozenset((_COMMON + "id origin_id operation phase original_id expected_history_version payload plan_digest").split()),
    "customer_partial_return_monetary_entries": frozenset((_COMMON + "plan_id purpose entry_id snapshot validation_digest original_effect_id posting_effect_id").split()),
    "customer_partial_return_monetary_events": frozenset((_COMMON + "plan_id operation actor_id reason audit_event_id outbox_event_id").split()),
    "customer_partial_return_monetary_history": frozenset((_COMMON + "origin_id sequence kind stock_fx_plan_id partial_plan_id original_sequence payload previous_digest event_digest").split()),
    "customer_partial_return_monetary_restorations": frozenset((_COMMON + "origin_id plan_id position original_consumption_id original_valuation_line_id cost_layer_id before_quantity_scaled before_value_minor quantity_scaled value_minor direction physical_movement_id correction_effect_id original_restoration_plan_id consumption_count_at_restore").split()),
    "customer_partial_return_monetary_commands": frozenset((_COMMON + "plan_id operation command_id actor_id request_digest request_json response_json").split()),
}
_PRIMARY = {
    "stock_sales_monetary_origins": ("tenant_id", "id"),
    "customer_partial_return_monetary_plans": ("tenant_id", "id"),
    "customer_partial_return_monetary_entries": ("tenant_id", "plan_id", "purpose"),
    "customer_partial_return_monetary_events": ("tenant_id", "plan_id", "operation"),
    "customer_partial_return_monetary_history": ("tenant_id", "origin_id", "sequence"),
    "customer_partial_return_monetary_restorations": ("tenant_id", "plan_id", "position"),
    "customer_partial_return_monetary_commands": ("tenant_id", "workspace_id", "command_id"),
}


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


def _new_row(table: str, row: dict[str, Any]) -> tuple[Any, ...] | None:
    """Pin the seven new storage shapes, without claiming deferred SQL closure."""
    if table not in MONETARY_COLUMNS:
        return None
    require(set(row) == MONETARY_COLUMNS[table])
    nullable = {"original_id", "original_effect_id", "posting_effect_id", "stock_fx_plan_id", "partial_plan_id",
                "original_sequence", "correction_effect_id", "original_restoration_plan_id"}
    numbers = {"phase", "expected_history_version", "sequence", "original_sequence", "position", "before_quantity_scaled",
               "before_value_minor", "quantity_scaled", "value_minor", "direction", "consumption_count_at_restore"}
    objects = {"payload", "ar_balance", "snapshot", "request_json", "response_json"}
    for field, value in row.items():
        if value is None:
            require(field in nullable)
        elif field in numbers:
            require(type(value) is int and -MAX_MINOR <= value <= MAX_MINOR)
        elif field in objects:
            require(type(value) is dict)
        elif field.endswith("_digest"):
            require(type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None)
        else:
            require(type(value) is str and 0 < len(value) <= (500 if field == "reason" else 140 if field == "command_id" else 160))
    if table.endswith("_plans"):
        prefixes = {"Return": "CR3", "Refund": "CRF3", "ReverseReturn": "CR3R", "ReverseRefund": "CRF3R"}
        require(row["operation"] in prefixes and 0 <= row["phase"] <= 3 and 0 <= row["expected_history_version"] <= 255)
        require(re.fullmatch(prefixes[row["operation"]] + r"-[a-f0-9]{32}", row["id"]) is not None)
        require((row["original_id"] is None) == (row["operation"] == "Return"))
    elif table.endswith("_entries"):
        purpose = row["purpose"]
        require(purpose in {"MerchandiseCredit", "CostRestoration", "Refund", "ReverseMerchandiseCredit", "ReverseCostRestoration", "ReverseRefund"})
        require(purpose.startswith("Reverse") == (row["original_effect_id"] is not None))
    elif table.endswith("_events"):
        require(row["operation"] in {"prepare", "review", "post", "cancel"})
    elif table.endswith("_history"):
        require(row["kind"] in {"Return", "Collection", "Refund", "ReverseReturn", "ReverseRefund"} and 1 <= row["sequence"] <= 256)
        require((row["stock_fx_plan_id"] is not None and row["partial_plan_id"] is None) if row["kind"] == "Collection"
                else (row["stock_fx_plan_id"] is None and row["partial_plan_id"] is not None))
        require((row["original_sequence"] is not None and 0 < row["original_sequence"] < row["sequence"])
                if row["kind"].startswith("Reverse") else row["original_sequence"] is None)
    elif table.endswith("_restorations"):
        require(1 <= row["position"] <= 32 and 1 <= row["quantity_scaled"] <= row["before_quantity_scaled"]
                and 0 <= row["value_minor"] <= row["before_value_minor"] and row["consumption_count_at_restore"] > 0)
        require(row["direction"] in {-1, 1} and (row["original_restoration_plan_id"] is None) == (row["direction"] == 1))
        # Zero individual portions may share a real positive plan-total effect.
        require(row["value_minor"] == 0 or row["correction_effect_id"] is not None)
    elif table.endswith("_commands"):
        require(row["operation"] in {"prepare", "prepare_refund", "prepare_reversal", "review", "post", "cancel"})
    return tuple(row[field] for field in _PRIMARY[table])


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
        keys: set[tuple[Any, ...]] = set()
        for row in rows:
            key = _new_row(name, _raw_row(row, tenant_id))
            if key is not None:
                require(key not in keys)
                keys.add(key)
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


def _minor(value: Any, *, positive: bool = False) -> int:
    require(type(value) is int and (1 if positive else 0) <= value <= MAX_MINOR)
    return cast(int, value)


def _digest(value: Any) -> str:
    try:
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    except (TypeError, ValueError, UnicodeError):
        raise MonetaryRawRefusal("Independent monetary raw input refused.") from None


def _one(capture: Capture, table: str, **fields: Any) -> dict[str, Any]:
    found = [row for row in capture.rows(table) if all(row.get(key) == value for key, value in fields.items())]
    require(len(found) == 1)
    return found[0]


def _scope(row: dict[str, Any], scope: dict[str, str]) -> None:
    require(all(type(row.get(key)) is str and row[key] == value for key, value in scope.items()))


def _nearest(value: Fraction, *, even: bool = False) -> int:
    require(type(value) is Fraction and value >= 0)
    low = value.numerator // value.denominator
    return _minor(min((low, low + 1), key=lambda n: (abs(value - n), n % 2 if even else -n)))


def _day(value: Any) -> str:
    require(type(value) is str and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None)
    try:
        require(date.fromisoformat(value).isoformat() == value)
    except ValueError:
        raise MonetaryRawRefusal("Independent monetary raw input refused.") from None
    return cast(str, value)


def _policy(value: Any) -> dict[str, Any]:
    require(type(value) is dict and set(value) == {"currency_code", "precision", "rounding_policy", "registry_version", "registry_digest"})
    require(type(value["precision"]) is int and 0 <= value["precision"] <= 8
            and type(value["currency_code"]) is str and re.fullmatch(r"[A-Z]{3}", value["currency_code"]) is not None
            and value["rounding_policy"] == "ROUND_HALF_UP"
            and type(value["registry_version"]) is str and bool(value["registry_version"])
            and type(value["registry_digest"]) is str and re.fullmatch(r"[a-f0-9]{64}", value["registry_digest"]) is not None)
    return value


def _full_policy(value: dict[str, Any]) -> dict[str, Any]:
    return {"currency_code": value["currency_code"], "currency_precision": value["precision"],
            "currency_rounding_policy": value["rounding_policy"], "currency_registry_version": value["registry_version"],
            "currency_registry_digest": value["registry_digest"]}


def _rate(value: Any, *, day: str) -> Fraction:
    require(type(value) is dict and set(value) == {"rate", "source", "effective_at"})
    require(type(value["rate"]) is str and len(value["rate"]) <= 96
            and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value["rate"]) is not None
            and type(value["source"]) is str and 0 < len(value["source"]) <= 200
            and value["source"].strip() == value["source"])
    require(type(value["effective_at"]) is str
            and re.fullmatch(re.escape(_day(day)) + r"T\d{2}:\d{2}:\d{2}Z", value["effective_at"]) is not None)
    try:
        datetime.fromisoformat(value["effective_at"].replace("Z", "+00:00"))
    except ValueError:
        raise MonetaryRawRefusal("Independent monetary raw input refused.") from None
    result = Fraction(value["rate"])
    require(result > 0)
    return result


def _effect(capture: Capture, effect_id: str, *, scope: dict[str, str], policy: dict[str, Any],
            expected: list[tuple[str, int, int]], external_reference: str,
            expected_dimensions: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
    """Join a real sealed effect to all its actual lines and dimensions."""
    effect = _one(capture, "finance_posting_effects", id=effect_id)
    _scope(effect, scope)
    entry = _one(capture, "finance_entries", id=effect["entry_id"])
    snapshot = effect["snapshot_json"]
    require(type(snapshot) is dict and set(snapshot) == {"schema_version", "entry", "lines"}
            and snapshot["schema_version"] == "finance-entry-review-v1" and type(snapshot["entry"]) is dict
            and type(snapshot["lines"]) is list and entry["status"] == "Validated"
            and effect["purpose"] == "operational_posting"
            and effect["validation_contract_version"] == entry["validation_contract_version"] == snapshot["schema_version"]
            and effect["validation_digest"] == entry["validation_digest"] == _digest(snapshot))
    header = snapshot["entry"]
    require(set(header) == {"id", "workspace_id", "organization_id", "legal_entity_id", "journal_id", "period_id", "entry_number",
                           "posting_date", "description", "external_reference", "source_type", "currency_code", "currency_precision",
                           "currency_rounding_policy", "currency_registry_version", "currency_registry_digest", "preparer_actor_id", "reverses_posting_id"})
    _scope(header, {key: value for key, value in scope.items() if key != "tenant_id"})
    for key, value in header.items():
        if key not in {"organization_id", "legal_entity_id"}:
            require(type(entry.get(key)) is type(value) and entry[key] == value)
    require(header["external_reference"] == external_reference)
    for obj in (effect, entry, header):
        require(all(type(obj.get(key)) is type(value) and obj[key] == value for key, value in policy.items()))
    people = (entry["preparer_actor_id"], entry["validator_actor_id"], effect["posted_actor_id"])
    require(all(type(person) is str and bool(person) for person in people) and len(set(people)) == 3)
    inverse = effect["reverses_effect_id"]
    if effect["source_kind"] == "InventoryReceipt":
        receipt = _one(capture, "inventory_receipt_plans", id=effect["source_id"])
        link = _one(capture, "inventory_receipt_links", plan_id=receipt["id"])
        review = _one(capture, "inventory_receipt_reviews", plan_id=receipt["id"])
        _scope(receipt, scope)
        _scope(link, scope)
        require(receipt["operation"] == "Receipt" and receipt["finance_entry_id"] == entry["id"] and receipt["posting_effect_id"] == effect["id"] == link["posting_effect_id"]
                and header["source_type"] == "Generated" and inverse is None and header["reverses_posting_id"] is None
                and header["external_reference"] == receipt["id"] and receipt["plan_digest"] == link["plan_digest"] == review["plan_digest"]
                and people == (receipt["preparer_actor_id"], review["reviewer_actor_id"], link["posted_actor_id"]))
    else:
        require(effect["source_kind"] == ("Reversal" if inverse else "Manual")
                and effect["source_id"] == (inverse if inverse else entry["id"])
                and header["source_type"] == ("Generated" if inverse else "Manual")
                and header["reverses_posting_id"] == inverse)
    lines = sorted((row for row in capture.rows("finance_entry_lines") if row["entry_id"] == entry["id"]), key=lambda row: _minor(row["line_number"], positive=True))
    require(len(lines) == len(expected) == len(snapshot["lines"]) >= 2)
    debit = credit = 0
    for index, (row, sealed, vector) in enumerate(zip(lines, snapshot["lines"], expected, strict=True), 1):
        account, dr, cr = vector
        require(set(sealed) == {"line_number", "account_id", "description", "debit_minor", "credit_minor", "dimensions"}
                and _minor(row["line_number"], positive=True) == index and row["currency_code"] == policy["currency_code"]
                and (row["account_id"], _minor(row["debit_minor"]), _minor(row["credit_minor"])) == (account, dr, cr)
                and min(dr, cr) == 0 < max(dr, cr)
                and all(type(sealed[key]) is type(row[key]) and sealed[key] == row[key] for key in set(sealed) - {"dimensions"}))
        dimensions = [item for item in capture.rows("finance_entry_line_dimensions") if item["entry_line_id"] == row["id"]]
        require(type(sealed["dimensions"]) is dict and len({item["dimension_id"] for item in dimensions}) == len(dimensions)
                and sealed["dimensions"] == {item["dimension_id"]: item["dimension_value_id"] for item in dimensions})
        if expected_dimensions is not None:
            require(account in expected_dimensions and sealed["dimensions"] == expected_dimensions[account])
        debit += dr
        credit += cr
    require(debit == credit == _minor(entry["total_debit_minor"], positive=True) == _minor(entry["total_credit_minor"], positive=True))
    _one(capture, "domain_audit_events", id=effect["audit_event_id"])
    _one(capture, "outbox_events", event_id=effect["outbox_event_id"])
    return effect


@dataclass(frozen=True)
class OriginalFinancial:
    """Independently joined original amounts, before any posted-history claim."""
    origin_id: str
    source: dict[str, Any]
    fingerprint: str
    roles: dict[str, str]
    scope: dict[str, str]
    components: tuple[tuple[int, int], ...]
    fifo: tuple[tuple[int, int], ...]


def verify_original_rows(capture: Capture, *, source_order_id: str) -> OriginalFinancial:
    """Re-derive positive-cost original Stock, tax/FX, AR and real COGS joins.

    This does not qualify a complete cycle or current authority. Restituted
    zero-cost original admission is refused until its separate native proof is
    joined; zero-valued subsequent return portions remain valid.
    """
    stock = _one(capture, "stock_sales_orders", id=_identity(source_order_id))
    scope = {key: _identity(stock[key]) for key in ("tenant_id", "workspace_id", "organization_id", "legal_entity_id")}
    origin = _one(capture, "stock_sales_monetary_origins", stock_order_id=stock["id"])
    _scope(origin, scope)
    require(stock["status"] in {"Invoiced", "CollectionPrepared", "CollectionReviewed", "Paid"}
            and stock["invoice_id"] == origin["invoice_id"] and stock["invoice_plan_id"] == origin["recognition_plan_id"])
    body = origin["payload"]
    require(type(body) is dict and set(body) == {"evidence", "source", "equation", "roles", "dimensions", "journal_id", "functional_policy", "refund_liability_account_code"}
            and origin["source_digest"] == _digest(body))
    source, declared = body["source"], stock["source"]
    require(type(source) is dict and type(declared) is dict and declared["schema_version"] == "stock-sales-monetary-order-v2"
            and stock["source_digest"] == _digest(declared))
    require(set(source) == {"source_id", "source_order_id", "invoice_id", "posting_date", "native_origin_digest", "quantity_scaled", "quantity_precision",
                            "transaction_policy", "functional_policy", "registry_snapshot", "components", "consumptions", "original_cost_admission_digest", "allocation_policy", "alignment_policy"})
    foreign, local = _policy(declared["monetary_policy"]), _policy(declared["functional_policy"])
    require((foreign["registry_version"], foreign["registry_digest"]) == (local["registry_version"], local["registry_digest"]))
    quantity, precision = _minor(stock["quantity_scaled"], positive=True), stock["quantity_precision"]
    require(type(precision) is int and 0 <= precision <= 6 and type(source["quantity_precision"]) is int and source["quantity_precision"] == precision
            and _minor(source["quantity_scaled"], positive=True) == quantity and _minor(declared["quantity_scaled"], positive=True) == quantity
            and type(declared["quantity"]) is str and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", declared["quantity"]) is not None
            and Fraction(declared["quantity"]) == Fraction(quantity, 10 ** precision))
    unit, discount = _minor(declared["unit_price_minor"], positive=True), _minor(declared["discount_basis_points"])
    require(discount <= 10_000)
    net_unit = _nearest(Fraction(unit * (10_000 - discount), 10_000))
    net = _nearest(Fraction(quantity * net_unit, 10 ** precision))
    require(net > 0 and _minor(declared["net_unit_price_minor"]) == net_unit
            and _minor(stock["total_minor"]) == _minor(declared["total_minor"]) == net)
    invoice = _one(capture, "ar_invoices", id=origin["invoice_id"])
    _scope(invoice, scope)
    require(invoice["customer_id"] == stock["customer_id"] and invoice["currency_code"] == foreign["currency_code"]
            and invoice["customer_partial_return_source_id"] is None)
    invoice_lines = [row for row in capture.rows("ar_invoice_lines") if row["invoice_id"] == invoice["id"]]
    require(len(invoice_lines) == 1)
    line = invoice_lines[0]
    require(_minor(line["line_number"], positive=True) == 1 and type(line["quantity"]) in {int, Fraction} and line["quantity"] == Fraction(quantity, 10 ** precision)
            and line["quantity_text"] == declared["quantity"] and _minor(line["unit_price_minor"]) == net_unit
            and _minor(line["line_total_minor"]) == net and line["description"] == declared["description"])
    fx = _one(capture, "operational_fx_sources", id=origin["fx_source_id"])
    _scope(fx, scope)
    original = fx["payload"]
    require(fx["invoice_id"] == invoice["id"] and original["schema_version"] == "operational-fx-stock-source-v2"
            and original["id"] == fx["id"] and original["invoice_id"] == invoice["id"]
            and original["stock_order_id"] == stock["id"] and original["stock_source_digest"] == stock["source_digest"]
            and original["source_digest"] == _digest({key: value for key, value in original.items() if key != "source_digest"}))
    _scope(original, {key: value for key, value in scope.items() if key != "tenant_id"})
    request, equation, roles = original["request"], body["equation"], body["roles"]
    require(equation == {key: value for key, value in original.items() if key not in {
        "schema_version", "id", "workspace_id", "organization_id", "legal_entity_id", "preparer_actor_id", "invoice_id", "source_digest", "stock_order_id", "stock_source_digest"}}
        and original["foreign_policy"] == _full_policy(foreign) and original["functional_policy"] == body["functional_policy"] == _full_policy(local)
        and _minor(request["net_minor"]) == net and request["foreign_currency_code"] == foreign["currency_code"]
        and invoice["invoice_date"] == _day(request["posting_date"]) and invoice["due_date"] == _day(request["due_date"]))
    _scope(request, {key: value for key, value in scope.items() if key != "tenant_id"})
    identity = foreign["currency_code"] == local["currency_code"]
    require(not identity or (foreign == local and request["original_rate"] is None))
    exchange = Fraction(1) if identity else _rate(request["original_rate"], day=request["posting_date"])
    scale = Fraction(10 ** local["precision"], 10 ** foreign["precision"])
    local_net = _nearest(net * exchange * scale)
    taxes = request["taxes"]
    require(type(taxes) is list and len(taxes) <= 8 and len({tax["policy_id"] for tax in taxes}) == len(taxes)
            and type(equation["tax_components"]) is list and len(equation["tax_components"]) == len(taxes))
    components = [(net, local_net)]
    gross, functional_gross = net, local_net
    for tax, retained in zip(taxes, equation["tax_components"], strict=True):
        require(type(tax) is dict and set(tax) == {"policy_id", "country_code", "transaction_class", "effective_from", "effective_to", "rate", "account_code", "source", "version", "policy_digest"}
                and tax["policy_digest"] == _digest({key: value for key, value in tax.items() if key != "policy_digest"})
                and tax["country_code"] == request["country_code"] and tax["transaction_class"] == request["transaction_class"]
                and _day(tax["effective_from"]) <= request["posting_date"] <= _day(tax["effective_to"])
                and type(tax["rate"]) is str and len(tax["rate"]) <= 96 and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", tax["rate"]) is not None)
        fraction = Fraction(tax["rate"])
        require(0 <= fraction <= 1)
        cut = _nearest(net * fraction)
        gross += cut
        converted = _nearest(gross * exchange * scale)
        functional_cut = converted - functional_gross
        require(_digest(retained) == _digest({**tax, "foreign_tax_minor": cut, "functional_tax_minor": functional_cut}))
        components.append((cut, functional_cut))
        functional_gross = converted
    require((_minor(invoice["subtotal_minor"]), _minor(invoice["tax_minor"]), _minor(invoice["total_minor"])) == (net, gross - net, gross)
            and _minor(line["tax_minor"]) == gross - net
            and [_minor(equation[key]) for key in ("foreign_net_minor", "foreign_tax_minor", "foreign_gross_minor", "functional_net_minor", "functional_gross_minor")]
            == [net, gross - net, gross, local_net, functional_gross])
    kinds = {"receivable": "Asset", "revenue": "Income", "cash": "Asset", "gain": "Income", "loss": "Expense", "refund_liability": "Liability", "inventory": "Asset", "cogs": "Expense"}
    require(type(roles) is dict and set(roles) == {key + "_account_id" for key in kinds} and len(set(roles.values())) == 8)
    for key, kind in kinds.items():
        account = _one(capture, "finance_accounts", id=roles[key + "_account_id"])
        require(account["workspace_id"] == scope["workspace_id"] and account["account_type"] == kind)
        if key not in {"inventory", "cogs"}:
            require(account["account_code"] == (body["refund_liability_account_code"] if key == "refund_liability" else request[key + "_account_code"]))
    typed = source["components"]
    require(type(typed) is list and len(typed) == len(components))
    for index, (part, amounts) in enumerate(zip(typed, components, strict=True)):
        account = roles["revenue_account_id"] if index == 0 else _one(capture, "finance_accounts", account_code=taxes[index - 1]["account_code"], workspace_id=scope["workspace_id"])["id"]
        require(set(part) == {"position", "kind", "account_id", "transaction_minor", "functional_minor", "policy_digest"}
                and type(part["position"]) is int and part["position"] == index and part["kind"] == ("Net" if index == 0 else "Tax")
                and part["account_id"] == account and (_minor(part["transaction_minor"]), _minor(part["functional_minor"])) == amounts
                and part["policy_digest"] == (_digest({"stock_source_digest": stock["source_digest"], "discount_policy": declared["discount_policy"]}) if index == 0 else taxes[index - 1]["policy_digest"]))
    recognition = _one(capture, "operational_fx_plans", id=origin["recognition_plan_id"])
    link = _one(capture, "operational_fx_links", plan_id=recognition["id"])
    require(recognition["source_id"] == fx["id"] and recognition["kind"] == "recognize" and _minor(recognition["sequence"]) == 0
            and type(recognition["phase"]) is int and recognition["phase"] == 2)
    expected = [(roles["receivable_account_id"], functional_gross, 0)]
    expected.extend((part["account_id"], 0, part["functional_minor"]) for part in typed if part["functional_minor"])
    revenue = _effect(capture, link["posting_effect_id"], scope=scope, policy=_full_policy(local), expected=expected,
                      external_reference="FX:" + fx["id"] + ":recognize")
    require(revenue["entry_id"] == recognition["entry_id"])
    consumptions = source["consumptions"]
    require(type(consumptions) is list and 1 <= len(consumptions) <= 32
            and len({part["original_consumption_id"] for part in consumptions}) == len(consumptions))
    fifo = []
    allocations = stock["issue_plan"]["allocations"]
    require(len(allocations) == len(consumptions))
    document = _one(capture, "inventory_valuation_documents", id=stock["valuation_id"])
    _scope(document, scope)
    require(document["status"] == "Approved" and document["movement_id"] == stock["movement_id"]
            and document["finance_entry_id"] == stock["cogs_entry_id"] and document["currency_code"] == local["currency_code"])
    for index, (part, allocation) in enumerate(zip(consumptions, allocations, strict=True), 1):
        consumed = _one(capture, "inventory_layer_consumptions", id=part["original_consumption_id"])
        valuation = _one(capture, "inventory_valuation_lines", id=consumed["valuation_line_id"])
        layer = _one(capture, "inventory_cost_layers", id=consumed["cost_layer_id"])
        require(type(part["position"]) is int and part["position"] == index and part["original_valuation_line_id"] == consumed["valuation_line_id"]
                and valuation["valuation_document_id"] == stock["valuation_id"] and valuation["item_id"] == stock["item_id"]
                and valuation["uom_id"] == layer["uom_id"] == stock["uom_id"] and valuation["flow_direction"] == "Outbound"
                and consumed["workspace_id"] == layer["workspace_id"] == scope["workspace_id"] and layer["legal_entity_id"] == scope["legal_entity_id"]
                and layer["item_id"] == stock["item_id"] and layer["currency_code"] == local["currency_code"]
                and part["cost_layer_id"] == allocation["cost_layer_id"] == layer["id"]
                and (_minor(part["quantity_scaled"], positive=True), _minor(part["value_minor"]))
                == (_minor(consumed["quantity_scaled"], positive=True), _minor(consumed["value_minor"]))
                == (_minor(allocation["quantity_scaled"], positive=True), _minor(allocation["value_minor"])))
        fifo.append((part["quantity_scaled"], part["value_minor"]))
    cost = _minor(sum(value for _, value in fifo), positive=True)
    require(sum(q for q, _ in fifo) == quantity and _minor(stock["issue_plan"]["total_cost_minor"]) == cost
            and source["original_cost_admission_digest"] is None and all(value > 0 for _, value in fifo))
    cogs = _effect(capture, stock["cogs_effect_id"], scope=scope, policy=_full_policy(local),
                   expected=[(roles["cogs_account_id"], cost, 0), (roles["inventory_account_id"], 0, cost)], external_reference=stock["id"])
    require(cogs["entry_id"] == stock["cogs_entry_id"])
    evidence = body["evidence"]
    require(type(evidence) is dict and set(evidence) == {"stock_order_id", "stock_source", "stock_source_digest", "issue_plan", "movement_id", "valuation_id",
        "cogs_entry_id", "cogs_effect_id", "cogs_snapshot", "fx_source", "recognition_plan_id", "recognition_snapshot", "invoice_id", "invoice_original", "invoice_line", "consumptions", "roles", "dimensions"})
    require(evidence["stock_order_id"] == stock["id"] and evidence["stock_source"] == declared and evidence["stock_source_digest"] == stock["source_digest"]
            and all(evidence[key] == stock[key] for key in ("issue_plan", "movement_id", "valuation_id", "cogs_entry_id", "cogs_effect_id", "invoice_id"))
            and evidence["cogs_snapshot"] == cogs["snapshot_json"] and evidence["recognition_snapshot"] == revenue["snapshot_json"]
            and evidence["fx_source"] == original and evidence["recognition_plan_id"] == recognition["id"]
            and evidence["consumptions"] == consumptions and evidence["roles"] == roles and evidence["dimensions"] == body["dimensions"]
            and evidence["invoice_original"] == {key: invoice[key] for key in ("customer_id", "currency_code", "invoice_number", "invoice_date", "due_date", "subtotal_minor", "tax_minor", "total_minor")})
    retained_line = evidence["invoice_line"]
    require(set(retained_line) == {"id", "invoice_id", "line_number", "quantity_text", "quantity_native_text", "unit_price_minor", "line_total_minor", "tax_minor", "description"}
            and all(retained_line[key] == line[key] for key in set(retained_line) - {"quantity_native_text"})
            and type(retained_line["quantity_native_text"]) is str and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", retained_line["quantity_native_text"]) is not None
            and Fraction(retained_line["quantity_native_text"]) == Fraction(quantity, 10 ** precision))
    require(source["source_id"] == origin["id"] and source["source_order_id"] == stock["id"] and source["invoice_id"] == invoice["id"]
            and source["transaction_policy"] == foreign and source["functional_policy"] == local
            and source["allocation_policy"] == "remaining-dual-currency-v1"
            and source["alignment_policy"] == "historical-carrying-component-alignment-v1"
            and source["posting_date"] == request["posting_date"]
            and source["registry_snapshot"]["digest"] == foreign["registry_digest"]
            and source["native_origin_digest"] == _digest(body["evidence"]))
    fingerprint = _digest({**{key: value for key, value in source.items() if key != "registry_snapshot"},
                           "schema_version": "customer-partial-return-monetary-original-v3",
                           "registry_digest": source["registry_snapshot"]["digest"]})
    return OriginalFinancial(origin["id"], source, fingerprint, roles, scope, tuple(components), tuple(fifo))


_MOVEMENT_FIELDS = ("transaction_net_minor", "transaction_tax_minor", "transaction_credit_minor", "functional_net_minor", "functional_tax_minor", "functional_credit_minor", "functional_cost_minor",
                    "transaction_receivable_released_minor", "functional_receivable_released_minor", "transaction_refund_delta_minor", "functional_refund_delta_minor", "transaction_refund_minor",
                    "functional_refund_released_minor", "functional_cash_minor", "functional_fx_gain_minor", "functional_fx_loss_minor", "functional_alignment_gain_minor", "functional_alignment_loss_minor", "functional_turnover_minor")


def _portion(value: int, quantity: int, selected: int, *, fifo: bool = False) -> int:
    _minor(value)
    _minor(quantity, positive=True)
    _minor(selected)
    require(selected <= quantity)
    return value if selected == quantity else _nearest(Fraction(value * selected, quantity), even=fifo)


def _initial(original: OriginalFinancial) -> dict[str, Any]:
    return {"remaining_quantity_scaled": original.source["quantity_scaled"],
            "component_transaction_minor": [f for f, _ in original.components], "component_functional_minor": [v for _, v in original.components],
            "consumption_quantity_scaled": [q for q, _ in original.fifo], "consumption_value_minor": [v for _, v in original.fifo],
            "transaction_outstanding_minor": sum(f for f, _ in original.components), "functional_outstanding_minor": sum(v for _, v in original.components),
            "transaction_refund_due_minor": 0, "functional_refund_due_minor": 0, "transaction_collected_minor": 0,
            "transaction_credited_minor": 0, "transaction_refunded_minor": 0, "functional_refund_released_minor": 0}


def _next_event(original: OriginalFinancial, previous: list[dict[str, Any]], supplied: dict[str, Any]) -> dict[str, Any]:
    """Fraction-distance allocation, separate from native NUMERIC/production code."""
    sequence = len(previous) + 1
    require(sequence <= 256 and type(supplied) is dict)
    kind, quantity, amount = supplied["kind"], _minor(supplied["quantity_scaled"]), _minor(supplied["amount_minor"])
    require(kind in {"Return", "Collection", "Refund", "ReverseReturn", "ReverseRefund"})
    day, rate, inverse = _day(supplied["posting_date"]), supplied["settlement_rate"], supplied["original_sequence"]
    require(day >= (previous[-1]["posting_date"] if previous else original.source["posting_date"]))
    before = previous[-1]["after"] if previous else _initial(original)
    after: dict[str, Any] = {key: list(value) if type(value) is list else value for key, value in before.items()}
    movement = dict.fromkeys(_MOVEMENT_FIELDS, 0)
    components: list[dict[str, Any]] = []
    portions: list[dict[str, Any]] = []
    if kind.startswith("Reverse"):
        require(rate is None and type(inverse) is int and 0 < inverse < sequence)
        active: list[int] = []
        for event in previous:
            if event["kind"].startswith("Reverse"):
                require(bool(active) and active[-1] == event["original_sequence"])
                active.pop()
            else:
                active.append(event["sequence"])
        require(bool(active) and active[-1] == inverse)
        parent = previous[inverse - 1]
        require(kind == "Reverse" + parent["kind"] and (quantity, amount) == (parent["quantity_scaled"], parent["amount_minor"])
                and _digest(before) == _digest(parent["after"]))
        after, movement, components, portions = parent["before"], parent["monetary"], parent["components"], parent["portions"]
    elif kind == "Return":
        remaining = _minor(before["remaining_quantity_scaled"], positive=True)
        require(0 < quantity <= remaining and amount == 0 and rate is None and inverse is None)
        for index, (foreign, local) in enumerate(zip(before["component_transaction_minor"], before["component_functional_minor"], strict=True)):
            cut_f, cut_l = _portion(foreign, remaining, quantity), _portion(local, remaining, quantity)
            components.append({"position": index, "before_quantity_scaled": remaining, "before_transaction_minor": foreign,
                               "before_functional_minor": local, "transaction_minor": cut_f, "functional_minor": cut_l})
            after["component_transaction_minor"][index] -= cut_f
            after["component_functional_minor"][index] -= cut_l
        cf, cl = sum(part["transaction_minor"] for part in components), sum(part["functional_minor"] for part in components)
        af = min(cf, before["transaction_outstanding_minor"])
        al = _portion(before["functional_outstanding_minor"], before["transaction_outstanding_minor"], af) if af else 0
        ef = cf - af
        el = _portion(cl, cf, ef) if ef else 0
        difference = cl - al - el
        pending = quantity
        for index, native in enumerate(original.source["consumptions"]):
            q, v = before["consumption_quantity_scaled"][index], before["consumption_value_minor"][index]
            take = min(pending, q)
            if take:
                cut = _portion(v, q, take, fifo=True)
                portions.append({"position": index + 1, **{key: native[key] for key in ("original_consumption_id", "original_valuation_line_id", "cost_layer_id")},
                                 "before_quantity_scaled": q, "before_value_minor": v, "quantity_scaled": take, "value_minor": cut})
                after["consumption_quantity_scaled"][index] -= take
                after["consumption_value_minor"][index] -= cut
                pending -= take
        require(pending == 0)
        cost = sum(part["value_minor"] for part in portions)
        movement.update(transaction_net_minor=components[0]["transaction_minor"], transaction_tax_minor=cf - components[0]["transaction_minor"], transaction_credit_minor=cf,
                        functional_net_minor=components[0]["functional_minor"], functional_tax_minor=cl - components[0]["functional_minor"], functional_credit_minor=cl,
                        functional_cost_minor=cost, transaction_receivable_released_minor=af, functional_receivable_released_minor=al,
                        transaction_refund_delta_minor=ef, functional_refund_delta_minor=el, functional_alignment_gain_minor=max(difference, 0),
                        functional_alignment_loss_minor=max(-difference, 0), functional_turnover_minor=cl + max(-difference, 0) + cost)
        after.update(remaining_quantity_scaled=remaining - quantity, transaction_outstanding_minor=before["transaction_outstanding_minor"] - af,
                     functional_outstanding_minor=before["functional_outstanding_minor"] - al,
                     transaction_refund_due_minor=before["transaction_refund_due_minor"] + ef, functional_refund_due_minor=before["functional_refund_due_minor"] + el,
                     transaction_credited_minor=before["transaction_credited_minor"] + cf)
    else:
        require(quantity == 0 and amount > 0 and inverse is None)
        refund = kind == "Refund"
        f_key, l_key = ("transaction_refund_due_minor", "functional_refund_due_minor") if refund else ("transaction_outstanding_minor", "functional_outstanding_minor")
        carrying_f, carrying_l = before[f_key], before[l_key]
        require(0 < amount <= carrying_f)
        released = _portion(carrying_l, carrying_f, amount)
        foreign, local = original.source["transaction_policy"], original.source["functional_policy"]
        if foreign["currency_code"] == local["currency_code"]:
            require(rate is None)
            cash = amount
        else:
            cash = _nearest(Fraction(amount * 10 ** local["precision"], 10 ** foreign["precision"]) * _rate(rate, day=day))
        delta = released - cash if refund else cash - released
        movement.update(functional_cash_minor=cash, functional_fx_gain_minor=max(delta, 0), functional_fx_loss_minor=max(-delta, 0), functional_turnover_minor=max(released, cash))
        if refund:
            movement.update(transaction_refund_minor=amount, functional_refund_released_minor=released)
            after["transaction_refunded_minor"] += amount
            after["functional_refund_released_minor"] += released
        else:
            movement.update(transaction_receivable_released_minor=amount, functional_receivable_released_minor=released)
            after["transaction_collected_minor"] += amount
        after[f_key], after[l_key] = carrying_f - amount, carrying_l - released
    for value in movement.values():
        _minor(value)
    for value in after.values():
        for scalar in value if type(value) is list else [value]:
            _minor(scalar)
    require((after["transaction_outstanding_minor"] > 0 or after["functional_outstanding_minor"] == 0)
            and (after["transaction_refund_due_minor"] > 0 or after["functional_refund_due_minor"] == 0))
    seed = {"contract": "customer-partial-return-monetary-original-v3", "source_fingerprint": original.fingerprint,
            "allocation_policy": "remaining-dual-currency-v1", "alignment_policy": "historical-carrying-component-alignment-v1"}
    return {"kind": kind, "sequence": sequence, "source_fingerprint": original.fingerprint,
            "previous_history_fingerprint": _digest(previous[-1]) if previous else _digest(seed), "posting_date": day,
            "quantity_scaled": quantity, "amount_minor": amount, "settlement_rate": rate, "original_sequence": inverse,
            "before": before, "after": after, "monetary": movement, "components": components, "portions": portions}


def verify_history_rows(capture: Capture, original: OriginalFinancial) -> tuple[dict[str, Any], ...]:
    """Reproduce every native history payload from original rows, not its sums."""
    rows = sorted((row for row in capture.rows("customer_partial_return_monetary_history") if row["origin_id"] == original.origin_id),
                  key=lambda row: _minor(row["sequence"], positive=True))
    require(len(rows) <= 256)
    events: list[dict[str, Any]] = []
    for sequence, row in enumerate(rows, 1):
        _scope(row, original.scope)
        require(_minor(row["sequence"], positive=True) == sequence and row["kind"] == row["payload"]["kind"])
        expected = _next_event(original, events, row["payload"])
        require(_digest(row["payload"]) == _digest(expected) and row["payload"] == expected
                and row["event_digest"] == _digest(expected) and row["previous_digest"] == expected["previous_history_fingerprint"]
                and row["original_sequence"] == expected["original_sequence"])
        if row["kind"] == "Collection":
            origin = _one(capture, "stock_sales_monetary_origins", id=original.origin_id)
            native = _one(capture, "operational_fx_plans", id=row["stock_fx_plan_id"])
            require(native["source_id"] == origin["fx_source_id"] and native["kind"] == "settle" and type(native["phase"]) is int and native["phase"] == 2
                    and native["payload"]["equation"]["monetary_event"] == expected)
        else:
            native = _one(capture, "customer_partial_return_monetary_plans", id=row["partial_plan_id"])
            require(native["origin_id"] == original.origin_id and native["operation"] == row["kind"] and type(native["phase"]) is int and native["phase"] == 2
                    and _minor(native["expected_history_version"]) == sequence - 1 and native["payload"]["monetary_event"] == expected
                    and native["plan_digest"] == _digest({key: value for key, value in native["payload"].items() if key != "plan_digest"})
                    == native["payload"]["plan_digest"])
        _scope(native, original.scope)
        events.append(expected)
    return tuple(events)


def _journals(original: OriginalFinancial, event: dict[str, Any]) -> list[tuple[str, list[tuple[str, int, int]]]]:
    """Finite original-account templates from independently derived magnitudes."""
    kind, movement, roles = event["kind"], event["monetary"], original.roles
    inverse = kind.startswith("Reverse")
    if inverse:
        kind = kind.removeprefix("Reverse")
    lines: list[tuple[str, int, int]] = []

    def leg(account: str, debit: int, credit: int) -> None:
        if debit or credit:
            require(min(_minor(debit), _minor(credit)) == 0 < max(debit, credit))
            lines.append((account, debit, credit))

    result: list[tuple[str, list[tuple[str, int, int]]]] = []
    if kind == "Return":
        for component, cut in zip(original.source["components"], event["components"], strict=True):
            leg(component["account_id"], cut["functional_minor"], 0)
        leg(roles["loss_account_id"], movement["functional_alignment_loss_minor"], 0)
        leg(roles["receivable_account_id"], 0, movement["functional_receivable_released_minor"])
        leg(roles["refund_liability_account_id"], 0, movement["functional_refund_delta_minor"])
        leg(roles["gain_account_id"], 0, movement["functional_alignment_gain_minor"])
        if lines:
            result.append(("MerchandiseCredit", lines))
        cost = movement["functional_cost_minor"]
        if cost:
            result.append(("CostRestoration", [(roles["inventory_account_id"], cost, 0), (roles["cogs_account_id"], 0, cost)]))
    elif kind == "Refund":
        leg(roles["refund_liability_account_id"], movement["functional_refund_released_minor"], 0)
        leg(roles["loss_account_id"], movement["functional_fx_loss_minor"], 0)
        leg(roles["cash_account_id"], 0, movement["functional_cash_minor"])
        leg(roles["gain_account_id"], 0, movement["functional_fx_gain_minor"])
        if lines:
            result.append(("Refund", lines))
    else:
        require(kind == "Collection")
        leg(roles["cash_account_id"], movement["functional_cash_minor"], 0)
        leg(roles["receivable_account_id"], 0, movement["functional_receivable_released_minor"])
        leg(roles["gain_account_id"], 0, movement["functional_fx_gain_minor"])
        leg(roles["loss_account_id"], movement["functional_fx_loss_minor"], 0)
        if lines:
            result.append(("Collection", lines))
    if inverse:
        result = [("Reverse" + purpose, [(account, cr, dr) for account, dr, cr in members]) for purpose, members in result]
    for _purpose, members in result:
        require(len(members) >= 2 and sum(dr for _, dr, _ in members) == sum(cr for _, _, cr in members) > 0)
    return result


def verify_posted_journal_rows(capture: Capture, original: OriginalFinancial,
                               events: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    """Bind each derived cash/correction journal to native posted memberships.

    Raw physical, global ledger deltas, observations and restore remain separate
    required gates; this function does not emit a complete-cycle proof.
    """
    origin = _one(capture, "stock_sales_monetary_origins", id=original.origin_id)
    dimensions, policy = origin["payload"]["dimensions"], _full_policy(original.source["functional_policy"])
    effect_ids: list[str] = []
    for event in events:
        history = _one(capture, "customer_partial_return_monetary_history", origin_id=original.origin_id, sequence=event["sequence"])
        vectors = _journals(original, event)
        if event["kind"] == "Collection":
            plan = _one(capture, "operational_fx_plans", id=history["stock_fx_plan_id"])
            link = _one(capture, "operational_fx_links", plan_id=plan["id"])
            receipt = _one(capture, "ar_receipts", id=link["receipt_id"])
            _scope(receipt, original.scope)
            require(receipt["status"] == "Posted" and receipt["currency_code"] == original.source["transaction_policy"]["currency_code"]
                    and _minor(receipt["amount_minor"], positive=True) == event["amount_minor"])
            allocations = [row for row in capture.rows("ar_receipt_allocations") if row["receipt_id"] == receipt["id"]]
            require(len(allocations) == 1 and allocations[0]["invoice_id"] == origin["invoice_id"]
                    and _minor(allocations[0]["amount_minor"], positive=True) == event["amount_minor"])
            if not vectors:
                require(event["monetary"]["functional_turnover_minor"] == 0 and plan["entry_id"] is None and link["posting_effect_id"] is None
                        and plan["payload"]["snapshot"] is None and plan["payload"]["validation_digest"] is None)
                continue
            require(len(vectors) == 1)
            effect = _effect(capture, link["posting_effect_id"], scope=original.scope, policy=policy, expected=vectors[0][1],
                             external_reference="FX:" + origin["fx_source_id"] + ":settle", expected_dimensions=dimensions)
            require(effect["entry_id"] == plan["entry_id"] and link["posted_actor_id"] == effect["posted_actor_id"])
            effect_ids.append(effect["id"])
            continue
        plan = _one(capture, "customer_partial_return_monetary_plans", id=history["partial_plan_id"])
        payload = plan["payload"]
        members = [row for row in capture.rows("customer_partial_return_monetary_entries") if row["plan_id"] == plan["id"]]
        require(len(members) == len(vectors) and {row["purpose"] for row in members} == {purpose for purpose, _ in vectors})
        retained_members = payload["entries"]
        require(type(retained_members) is list and len(retained_members) == len(members)
                and {part["purpose"] for part in retained_members} == {purpose for purpose, _ in vectors})
        people = [_one(capture, "customer_partial_return_monetary_events", plan_id=plan["id"], operation=op)["actor_id"] for op in ("prepare", "review", "post")]
        require(len(set(people)) == 3 and payload["preparer_actor_id"] == people[0])
        for purpose, lines in vectors:
            member = _one(capture, "customer_partial_return_monetary_entries", plan_id=plan["id"], purpose=purpose)
            _scope(member, original.scope)
            retained = [part for part in retained_members if part["purpose"] == purpose]
            require(len(retained) == 1 and all(retained[0][key] == member[key] for key in
                    ("purpose", "entry_id", "snapshot", "validation_digest", "original_effect_id")))
            original_effect = member["original_effect_id"]
            if event["kind"].startswith("Reverse"):
                parent_history = _one(capture, "customer_partial_return_monetary_history", origin_id=original.origin_id, sequence=event["original_sequence"])
                parent = _one(capture, "customer_partial_return_monetary_entries", plan_id=parent_history["partial_plan_id"], purpose=purpose.removeprefix("Reverse"))
                require(plan["original_id"] == parent["plan_id"] and original_effect == parent["posting_effect_id"])
            else:
                require(original_effect is None)
            suffix = "C" if purpose.endswith("CostRestoration") else "F" if purpose.endswith("Refund") else "R"
            number = plan["id"].upper() + "-" + suffix
            identifier = "GLE-" + hashlib.sha256((original.scope["workspace_id"] + "|" + number).encode()).hexdigest()[:16]
            require(member["entry_id"] == identifier)
            effect = _effect(capture, member["posting_effect_id"], scope=original.scope, policy=policy, expected=lines,
                             external_reference=original_effect if original_effect is not None else plan["id"], expected_dimensions=dimensions)
            entry = _one(capture, "finance_entries", id=identifier)
            require(entry["entry_number"] == number and effect["entry_id"] == identifier and member["snapshot"] == effect["snapshot_json"]
                    and member["validation_digest"] == effect["validation_digest"] and effect["reverses_effect_id"] == original_effect
                    and entry["preparer_actor_id"] == people[0] and entry["validator_actor_id"] == people[1] and effect["posted_actor_id"] == people[2])
            effect_ids.append(effect["id"])
    require(len(effect_ids) == len(set(effect_ids)))
    return tuple(effect_ids)


def verify_physical_rows(capture: Capture, original: OriginalFinancial,
                         events: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    """All actual CR3 movement/restoration memberships, including zero cost."""
    stock = _one(capture, "stock_sales_orders", id=original.source["source_order_id"])
    movement_ids: list[str] = []
    for event in events:
        history = _one(capture, "customer_partial_return_monetary_history", origin_id=original.origin_id, sequence=event["sequence"])
        if event["kind"] == "Collection":
            continue
        plan = _one(capture, "customer_partial_return_monetary_plans", id=history["partial_plan_id"])
        payload = plan["payload"]
        restorations = [row for row in capture.rows("customer_partial_return_monetary_restorations") if row["plan_id"] == plan["id"]]
        if event["kind"] in {"Refund", "ReverseRefund"}:
            require(not restorations and payload["movement_id"] is None)
            continue
        reverse = event["kind"] == "ReverseReturn"
        require(event["kind"] in {"Return", "ReverseReturn"})
        number = plan["id"].upper()
        identifier = "MOV-" + hashlib.sha256((original.scope["workspace_id"] + "|" + number).encode()).hexdigest()[:16]
        require(payload["movement_id"] == identifier and payload["quantity_scaled"] == event["quantity_scaled"])
        movement = _one(capture, "inventory_movements", id=identifier)
        _scope(movement, original.scope)
        require(movement["movement_number"] == number and movement["source_reference"] == plan["id"]
                and movement["source_type"] == "Generated" and movement["status"] == "Posted"
                and movement["movement_type"] == ("Delivery" if reverse else "Receipt")
                and movement["movement_date"] == payload["posting_date"] == event["posting_date"]
                and movement["period_id"] == payload["period_id"])
        line = _one(capture, "inventory_movement_lines", movement_id=identifier)
        require(line["item_id"] == stock["item_id"] and line["uom_id"] == stock["uom_id"]
                and _minor(line["quantity_scaled"], positive=True) == event["quantity_scaled"]
                and type(line["quantity_precision"]) is int and line["quantity_precision"] == original.source["quantity_precision"]
                and line["from_location_id"] == (stock["location_id"] if reverse else None)
                and line["to_location_id"] == (None if reverse else stock["location_id"]) and line["inventory_lot_id"] is None)
        require(len(restorations) == len(event["portions"]))
        cost_purpose = "ReverseCostRestoration" if reverse else "CostRestoration"
        cost_entries = [row for row in capture.rows("customer_partial_return_monetary_entries") if row["plan_id"] == plan["id"] and row["purpose"] == cost_purpose]
        require(len(cost_entries) == (1 if event["monetary"]["functional_cost_minor"] > 0 else 0))
        cost_effect = cost_entries[0]["posting_effect_id"] if cost_entries else None
        for portion in event["portions"]:
            restored = _one(capture, "customer_partial_return_monetary_restorations", plan_id=plan["id"], position=portion["position"])
            _scope(restored, original.scope)
            require(all(type(restored[key]) is type(value) and restored[key] == value for key, value in portion.items())
                    and restored["origin_id"] == original.origin_id and restored["direction"] == (-1 if reverse else 1)
                    and restored["physical_movement_id"] == identifier and restored["correction_effect_id"] == cost_effect
                    and restored["original_restoration_plan_id"] == (plan["original_id"] if reverse else None))
            consumed = [row for row in capture.rows("inventory_layer_consumptions") if row["cost_layer_id"] == restored["cost_layer_id"]]
            require(0 < _minor(restored["consumption_count_at_restore"], positive=True) <= len(consumed))
            if reverse:
                parent = _one(capture, "customer_partial_return_monetary_restorations", plan_id=plan["original_id"], position=portion["position"])
                require(parent["origin_id"] == original.origin_id and parent["consumption_count_at_restore"] == len(consumed))
        movement_ids.append(identifier)
    require(len(movement_ids) == len(set(movement_ids)))
    for native in original.source["consumptions"]:
        layer_id = native["cost_layer_id"]
        layer = _one(capture, "inventory_cost_layers", id=layer_id)
        consumed = [row for row in capture.rows("inventory_layer_consumptions") if row["cost_layer_id"] == layer_id]
        corrections = [row for table in ("customer_partial_return_restorations", "customer_partial_return_monetary_restorations")
                       for row in capture.rows(table) if row["cost_layer_id"] == layer_id]
        quantity = _minor(layer["original_quantity_scaled"], positive=True) - sum(_minor(row["quantity_scaled"], positive=True) for row in consumed)
        value = _minor(layer["original_value_minor"], positive=True) - sum(_minor(row["value_minor"]) for row in consumed)
        for row in corrections:
            require(type(row["direction"]) is int and row["direction"] in {-1, 1})
            quantity += row["direction"] * _minor(row["quantity_scaled"], positive=True)
            value += row["direction"] * _minor(row["value_minor"])
        require((_minor(layer["remaining_quantity_scaled"]), _minor(layer["remaining_value_minor"])) == (quantity, value)
                and 0 <= quantity <= layer["original_quantity_scaled"] and 0 <= value <= layer["original_value_minor"])
    return tuple(movement_ids)


def verify_valuation_rows(capture: Capture, original: OriginalFinancial,
                          events: tuple[dict[str, Any], ...]) -> tuple[tuple[str, ...], str | None]:
    """Independently value the witnessed credit-adjusted carrying, then invert."""
    origin = _one(capture, "stock_sales_monetary_origins", id=original.origin_id)
    plans = sorted((row for row in capture.rows("operational_fx_plans") if row["source_id"] == origin["fx_source_id"]),
                   key=lambda row: _minor(row["sequence"]))
    active: str | None = None
    effects: list[str] = []
    foreign, local = original.source["transaction_policy"], original.source["functional_policy"]
    for sequence, native in enumerate(plans):
        _scope(native, original.scope)
        require(_minor(native["sequence"]) == sequence and type(native["phase"]) is int and native["phase"] == 2)
        kind = native["kind"]
        if kind in {"recognize", "settle"}:
            require((kind == "recognize") == (sequence == 0))
            continue
        require(kind in {"revalue", "reverse_revaluation"} and foreign["currency_code"] != local["currency_code"])
        body = native["payload"]
        require(body["source_id"] == origin["fx_source_id"] and body["id"] == native["id"] and body["kind"] == kind
                and body["sequence"] == sequence and body["entry_id"] == native["entry_id"]
                and body["plan_digest"] == _digest({key: value for key, value in body.items() if key not in {"plan_digest", "validation_digest"}}))
        equation = body["equation"]
        if kind == "revalue":
            require(active is None)
            basis = equation["monetary_history_basis"]
            require(type(basis) is dict and set(basis) == {"source_fingerprint", "history_version", "history_fingerprint"}
                    and basis["source_fingerprint"] == original.fingerprint)
            version = _minor(basis["history_version"])
            require(version <= len(events))
            prefix = list(events[:version])
            state = prefix[-1]["after"] if prefix else _initial(original)
            seed = {"contract": "customer-partial-return-monetary-original-v3", "source_fingerprint": original.fingerprint,
                    "allocation_policy": "remaining-dual-currency-v1", "alignment_policy": "historical-carrying-component-alignment-v1"}
            require(basis["history_fingerprint"] == _digest(prefix[-1] if prefix else seed))
            outstanding, carrying = _minor(state["transaction_outstanding_minor"], positive=True), _minor(state["functional_outstanding_minor"])
            valued = _nearest(Fraction(outstanding * 10 ** local["precision"], 10 ** foreign["precision"]) * _rate(equation["closing_rate"], day=body["posting_date"]))
            delta = valued - carrying
            require(delta != 0)
            gain = _one(capture, "finance_accounts", workspace_id=original.scope["workspace_id"], account_code=equation["unrealized_gain_account_code"])
            loss = _one(capture, "finance_accounts", workspace_id=original.scope["workspace_id"], account_code=equation["unrealized_loss_account_code"])
            forbidden = {*original.roles.values(), *(part["account_id"] for part in original.source["components"])}
            require(gain["id"] != loss["id"] and gain["account_type"] == "Income" and loss["account_type"] == "Expense"
                    and gain["id"] not in forbidden and loss["id"] not in forbidden)
            amount = abs(delta)
            expected_lines = [(original.roles["receivable_account_id"], max(delta, 0), max(-delta, 0)),
                              (gain["id"] if delta > 0 else loss["id"], max(-delta, 0), max(delta, 0))]
            expected_equation = {"foreign_before_minor": sum(f for f, _ in original.components) - outstanding,
                                 "historical_before_minor": sum(v for _, v in original.components) - carrying,
                                 "foreign_outstanding_minor": outstanding, "historical_outstanding_minor": carrying,
                                 "valued_outstanding_minor": valued, "unrealized_fx_minor": delta,
                                 "closing_rate": equation["closing_rate"], "unrealized_gain_account_code": gain["account_code"],
                                 "unrealized_loss_account_code": loss["account_code"], "amount_minor": amount,
                                 "monetary_history_basis": basis,
                                 "lines": [{"account_code": _one(capture, "finance_accounts", id=account)["account_code"], "debit_minor": dr, "credit_minor": cr} for account, dr, cr in expected_lines]}
            require(_digest(equation) == _digest(expected_equation))
            original_effect = None
            active = native["id"]
        else:
            require(active is not None and equation["original_revaluation_id"] == active)
            parent = _one(capture, "operational_fx_plans", id=active)
            parent_link = _one(capture, "operational_fx_links", plan_id=active)
            prior = parent["payload"]["equation"]
            expected_equation = {"original_revaluation_id": active, "original_plan_digest": parent["payload"]["plan_digest"],
                                 "original_posting_effect_id": parent_link["posting_effect_id"], "original_equation_digest": _digest(prior),
                                 "unrealized_fx_minor": -prior["unrealized_fx_minor"], "amount_minor": prior["amount_minor"],
                                 "lines": [{"account_code": line["account_code"], "debit_minor": line["credit_minor"], "credit_minor": line["debit_minor"]} for line in prior["lines"]]}
            require(_digest(equation) == _digest(expected_equation) and _day(body["posting_date"]) >= _day(parent["payload"]["posting_date"]))
            expected_lines = [(_one(capture, "finance_accounts", workspace_id=original.scope["workspace_id"], account_code=line["account_code"])["id"], line["debit_minor"], line["credit_minor"]) for line in expected_equation["lines"]]
            original_effect = parent_link["posting_effect_id"]
            active = None
        link = _one(capture, "operational_fx_links", plan_id=native["id"])
        effect = _effect(capture, link["posting_effect_id"], scope=original.scope, policy=_full_policy(local), expected=expected_lines,
                         external_reference=original_effect if original_effect is not None else "FX:" + origin["fx_source_id"] + ":revalue",
                         expected_dimensions={account: {} for account, _, _ in expected_lines})
        review = _one(capture, "operational_fx_reviews", plan_id=native["id"])
        entry = _one(capture, "finance_entries", id=native["entry_id"])
        require(body["amount_minor"] == equation["amount_minor"] and effect["entry_id"] == native["entry_id"] and effect["reverses_effect_id"] == original_effect
                and body["snapshot"] == effect["snapshot_json"] and body["validation_digest"] == effect["validation_digest"]
                and entry["preparer_actor_id"] == body["preparer_actor_id"] and entry["validator_actor_id"] == review["reviewer_actor_id"]
                and effect["posted_actor_id"] == link["posted_actor_id"])
        effects.append(effect["id"])
    return tuple(effects), active


AUDIT_TABLES = frozenset({"domain_audit_events", "domain_audit_ledger_state"})
_AUDIT_FIELDS = frozenset({"tenant_id", "id", "sequence", "previous_hash", "event_hash", "actor_user_id", "actor_label", "object_type", "object_id", "action", "before_hash", "after_hash", "metadata_json", "created_at"})
_POLICY_FIELDS = frozenset({"actor_digest", "allowed", "context_binding", "context_digest", "decision_digest", "evaluator", "granted_permission_digest", "policy_version", "principal_type", "reason_code", "request_id_digest", "required_permission_digest", "schema_version", "scope_digest", "surface_digest"})
_READ = frozenset({"sales.read", "receivables.read", "inventory.read", "finance_core.read"})
_POST = _READ | {"sales.manage", "receivables.manage", "inventory.post", "inventory.valuation.approve", "finance_core.post", "finance_core.reverse"}
_PREPARE = _READ | {"sales.manage", "receivables.manage", "inventory.valuation.manage", "finance_core.manage", "finance_core.reverse"}


def _audit_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, UnicodeError):
        raise MonetaryRawRefusal("Independent monetary raw input refused.") from None


def _audit_digest(value: Any) -> str:
    return hashlib.sha256(_audit_json(value).encode()).hexdigest()


def _text_digest(namespace: str, value: str) -> str:
    return _audit_digest({"namespace": namespace, "value": value})


def _hex(value: Any) -> str:
    require(type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None)
    return cast(str, value)


def _audit_chain(capture: Capture, tenant: str) -> tuple[str, ...]:
    originals = dict(capture.raw_tables)["domain_audit_events"]
    rows = sorted(((_decode(raw), raw) for raw in originals), key=lambda pair: _minor(pair[0]["sequence"], positive=True))
    seen: set[str] = set()
    previous = "0" * 64
    for sequence, (row, _raw) in enumerate(rows, 1):
        require(set(row) == _AUDIT_FIELDS and row["tenant_id"] == tenant and _minor(row["sequence"], positive=True) == sequence
                and row["previous_hash"] == previous and _identity(row["id"]) not in seen)
        seen.add(row["id"])
        require(all(type(row[key]) is str and 0 < len(row[key]) <= 500 for key in ("actor_label", "object_type", "object_id", "action", "created_at"))
                and (row["actor_user_id"] is None or type(row["actor_user_id"]) is str)
                and all(row[key] is None or type(row[key]) is str for key in ("before_hash", "after_hash"))
                and type(row["metadata_json"]) is dict)
        signed = {key: row[key] for key in _AUDIT_FIELDS - {"tenant_id", "event_hash"}}
        signed["metadata_json"] = _audit_json(row["metadata_json"])
        previous = _audit_digest(signed)
        require(_hex(row["event_hash"]) == previous)
    heads = capture.rows("domain_audit_ledger_state")
    require(len(heads) == 1 or not rows and not heads)
    if heads:
        require(set(heads[0]) == {"tenant_id", "last_sequence", "last_event_hash", "updated_at"}
                and heads[0]["tenant_id"] == tenant and _minor(heads[0]["last_sequence"]) == len(rows)
                and _hex(heads[0]["last_event_hash"]) == previous
                and (not rows or heads[0]["updated_at"] == rows[-1][0]["created_at"]))
    return tuple(raw for _, raw in rows)


def _policy_surfaces(capture: Capture) -> tuple[dict[str, frozenset[str]], set[str]]:
    orders = capture.rows("stock_sales_orders")
    require(len(orders) == 1)
    order = orders[0]["id"]
    surfaces = {"GET /api/v1/stock-sales/orders": _READ, "GET /api/v1/stock-sales/options": _READ,
                "GET /api/v2/stock-sales/orders": _READ, "GET /api/v2/stock-sales/options": _READ,
                "GET /api/v2/stock-sales/orders/" + order: _READ,
                "GET /api/v1/customer-returns/plans": _READ, "GET /api/v3/customer-partial-returns/plans": _READ,
                "GET /api/v3/customer-partial-returns/sources/" + order + "/balance": _READ,
                "POST /api/v3/customer-partial-returns/plans": _PREPARE,
                "server.scoped:finance_core.read": frozenset({"finance_core.read"})}
    actors = {value for row in capture.rows("finance_posting_effects") for value in
              (row["posted_actor_id"], row["snapshot_json"]["entry"]["preparer_actor_id"])}
    actors.update(row["validator_actor_id"] for row in capture.rows("finance_entries") if row.get("validator_actor_id"))
    actors.update(row["actor_id"] for row in capture.rows("customer_partial_return_monetary_events"))
    for plan in capture.rows("customer_partial_return_monetary_plans"):
        surfaces["GET /api/v3/customer-partial-returns/plans/" + plan["id"]] = _READ
        if plan["phase"] == 2:
            surfaces["POST /api/v3/customer-partial-returns/plans/" + plan["id"] + "/post"] = _POST
    for plan in capture.rows("operational_fx_plans"):
        surfaces["GET /api/v2/stock-sales/orders/" + order + "/fx-plans/" + plan["id"]] = _READ
    for suffix, permission in (("audit/events", "audit.read"), ("audit/verify", "audit.verify"), ("security/overview", "security.center.read"),
                               ("identity/users", "users.manage"), ("identity/sessions", "users.manage"), ("access/permissions", "roles.manage"),
                               ("access/roles", "roles.manage"), ("security/integrations", "security.policy.manage"), ("security/retention-policies", "security.policy.manage")):
        surfaces["GET /api/v1/admin/" + suffix] = frozenset({permission})
        surfaces["server.scoped:" + permission] = frozenset({permission})
    return {_text_digest("audit.surface", key): value for key, value in surfaces.items()}, actors


def _policy_append(row: dict[str, Any], capture: Capture, *, scope_refusal: bool = False) -> None:
    require(row["actor_label"] == "policy-engine" and row["object_type"] == "authorization.policy_decision" and row["action"] == "evaluated" and row["before_hash"] is None)
    metadata = row["metadata_json"]
    require(set(metadata) == {"policy_decision_evidence", "request_id_digest"})
    policy = metadata["policy_decision_evidence"]
    require(type(policy) is dict and set(policy) == _POLICY_FIELDS and type(policy["schema_version"]) is int and policy["schema_version"] == 1
            and policy["policy_version"] == "central-policy-v3" and policy["principal_type"] == "user" and policy["context_binding"] == "bound"
            and type(policy["allowed"]) is bool and type(policy["evaluator"]) is str and 0 < len(policy["evaluator"]) <= 160
            and type(policy["reason_code"]) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,119}", policy["reason_code"]) is not None)
    for key in _POLICY_FIELDS - {"schema_version", "allowed", "policy_version", "principal_type", "context_binding", "evaluator", "reason_code", "granted_permission_digest"}:
        _hex(policy[key])
    require(policy["decision_digest"] == _audit_digest({key: value for key, value in policy.items() if key != "decision_digest"})
            == row["object_id"] == row["after_hash"] and metadata["request_id_digest"] == policy["request_id_digest"])
    surfaces, actors = _policy_surfaces(capture)
    actor = row["actor_user_id"]
    require(actor in actors and policy["actor_digest"] == _text_digest("principal.actor", actor.strip().casefold()))
    permissions = surfaces.get(policy["surface_digest"])
    require(permissions is not None)
    permissions = cast(frozenset[str], permissions)
    required = {permission for permission in permissions if policy["required_permission_digest"] == _audit_digest({"namespace": "permission.contract", "values": [permission]})}
    require(len(required) == 1)
    if policy["allowed"]:
        require(policy["granted_permission_digest"] == _text_digest("permission.granted", next(iter(required))))
    else:
        orders = capture.rows("stock_sales_orders")
        require(scope_refusal and policy["reason_code"] in {"entity_scope_denied", "organization_scope_denied", "workspace_scope_denied", "tenant_scope_denied"}
                and policy["surface_digest"] in {_text_digest("audit.surface", "server.scoped:finance_core.read"),
                                                  _text_digest("audit.surface", "GET /api/v3/customer-partial-returns/sources/" + orders[0]["id"] + "/balance")}
                and policy["granted_permission_digest"] is None)


def verify_audit_only_transition(before_tables: dict[str, Any], after_tables: dict[str, Any], *, tenant_id: str,
                                 scope_refusal: bool = False) -> dict[str, Any]:
    before = decode_capture({"capture": 0, "tables": before_tables}, index=0, tenant_id=tenant_id)
    after = decode_capture({"capture": 0, "tables": after_tables}, index=0, tenant_id=tenant_id)
    old_tables, new_tables = dict(before.raw_tables), dict(after.raw_tables)
    require(all(old_tables[name] == new_tables[name] for name in TABLES if name not in AUDIT_TABLES))
    old, new = _audit_chain(before, tenant_id), _audit_chain(after, tenant_id)
    require(new[:len(old)] == old)
    for raw in new[len(old):]:
        _policy_append(_decode(raw), after, scope_refusal=scope_refusal)
    return {"business_tables": 89, "business_original_rows_equal": True, "audit_original_prefix_equal": True,
            "audit_chain_valid": True, "audit_actions_bound": True, "appended_audit_events": len(new) - len(old)}


def _ledger(capture: Capture, original: OriginalFinancial, allowed: set[str]) -> tuple[int, int, int]:
    effects = capture.rows("finance_posting_effects")
    require(len({row["id"] for row in effects}) == len(effects) and {row["id"] for row in effects} == allowed)
    lines = count = debit = credit = 0
    for effect in effects:
        entry = _one(capture, "finance_entries", id=effect["entry_id"])
        observed = sorted((row for row in capture.rows("finance_entry_lines") if row["entry_id"] == entry["id"]), key=lambda row: _minor(row["line_number"], positive=True))
        left = sum(_minor(row["debit_minor"]) for row in observed)
        right = sum(_minor(row["credit_minor"]) for row in observed)
        require(left == right == _minor(entry["total_debit_minor"], positive=True) == _minor(entry["total_credit_minor"], positive=True))
        lines += len(observed)
        count += 1
        debit += left
        credit += right
    require(debit == credit)
    for entry in capture.rows("finance_entries"):
        if any(effect["entry_id"] == entry["id"] for effect in effects):
            continue
        member = _one(capture, "customer_partial_return_monetary_entries", entry_id=entry["id"])
        owner = _one(capture, "customer_partial_return_monetary_plans", id=member["plan_id"])
        require(owner["origin_id"] == original.origin_id and owner["phase"] == 3 and entry["status"] == "Voided" and member["posting_effect_id"] is None)
    return count, lines, debit


def _receipt_effects(capture: Capture, original: OriginalFinancial) -> set[str]:
    result: set[str] = set()
    for link in capture.rows("inventory_receipt_links"):
        plan = _one(capture, "inventory_receipt_plans", id=link["plan_id"])
        value = _minor(plan["total_value_minor"], positive=True)
        _effect(capture, link["posting_effect_id"], scope=original.scope, policy=_full_policy(original.source["functional_policy"]),
                expected=[(plan["inventory_account_id"], value, 0), (plan["receipt_clearing_account_id"], 0, value)], external_reference=plan["id"])
        result.add(link["posting_effect_id"])
    return result


def _projection(capture: Capture, original: OriginalFinancial, events: tuple[dict[str, Any], ...], active: str | None) -> None:
    origin = _one(capture, "stock_sales_monetary_origins", id=original.origin_id)
    state = events[-1]["after"] if events else _initial(original)
    gf, gl = sum(f for f, _ in original.components), sum(v for _, v in original.components)
    ef = max(state["transaction_collected_minor"] + state["transaction_credited_minor"] - gf, 0)
    el = state["functional_refund_due_minor"] + state["functional_refund_released_minor"]
    seed = {"contract": "customer-partial-return-monetary-original-v3", "source_fingerprint": original.fingerprint,
            "allocation_policy": "remaining-dual-currency-v1", "alignment_policy": "historical-carrying-component-alignment-v1"}
    book = state["functional_outstanding_minor"]
    if active is not None:
        book = _one(capture, "operational_fx_plans", id=active)["payload"]["equation"]["valued_outstanding_minor"]
    expected: dict[str, Any] = {"schema_version": "stock-monetary-balance-v1", "history_version": len(events),
        "history_fingerprint": _digest(events[-1] if events else seed), "transaction_original_gross_minor": str(gf), "functional_original_gross_minor": str(gl),
        "transaction_collected_minor": str(state["transaction_collected_minor"]), "transaction_credited_minor": str(state["transaction_credited_minor"]),
        "transaction_outstanding_minor": str(state["transaction_outstanding_minor"]), "functional_outstanding_minor": str(book),
        "transaction_refund_entitlement_minor": str(ef), "functional_refund_entitlement_minor": str(el),
        "transaction_refunded_minor": str(state["transaction_refunded_minor"]), "functional_refund_released_minor": str(state["functional_refund_released_minor"]),
        "transaction_refund_due_minor": str(state["transaction_refund_due_minor"]), "functional_refund_due_minor": str(state["functional_refund_due_minor"]),
        "active_plan_id": None, "active_revaluation_plan_id": active}
    require(_digest(origin["ar_balance"]) == _digest(expected))
    invoice = _one(capture, "ar_invoices", id=origin["invoice_id"])
    allocations = [row for row in capture.rows("ar_receipt_allocations") if row["invoice_id"] == invoice["id"]]
    require(sum(_minor(row["amount_minor"], positive=True) for row in allocations) == state["transaction_collected_minor"]
            and invoice["status"] == ("Paid" if state["transaction_outstanding_minor"] == 0 else "Approved" if state["transaction_collected_minor"] == 0 else "PartiallyPaid"))


def _native_memberships(capture: Capture, original: OriginalFinancial) -> None:
    """Bind new owner rows to their native parents and immutable evidence IDs."""
    require(len(capture.rows("stock_sales_monetary_origins")) == 1)
    plans = capture.rows("customer_partial_return_monetary_plans")
    for plan in plans:
        _scope(plan, original.scope)
        require(plan["origin_id"] == original.origin_id)
        body = plan["payload"]
        require(body["id"] == plan["id"] and body["source_id"] == original.origin_id
                and body["source_order_id"] == original.source["source_order_id"]
                and body["operation"] == plan["operation"] and body["original_id"] == plan["original_id"]
                and body["plan_digest"] == plan["plan_digest"]
                and plan["plan_digest"] == _digest({key: value for key, value in body.items() if key != "plan_digest"}))
        operations = {row["operation"] for row in capture.rows("customer_partial_return_monetary_events") if row["plan_id"] == plan["id"]}
        permitted = [{"prepare", "review", "post"}] if plan["phase"] == 2 else [{"prepare", "cancel"}, {"prepare", "review", "cancel"}] if plan["phase"] == 3 else [{"prepare", "review"}] if plan["phase"] == 1 else [{"prepare"}]
        require(operations in permitted)
        commands = {"prepare" if row["operation"].startswith("prepare") else row["operation"] for row in capture.rows("customer_partial_return_monetary_commands") if row["plan_id"] == plan["id"]}
        require(commands == operations)
    for row in capture.rows("customer_partial_return_monetary_events"):
        _scope(row, original.scope)
        plan = _one(capture, "customer_partial_return_monetary_plans", id=row["plan_id"])
        action = "customer_partial_return_monetary_" + row["operation"]
        audit = _one(capture, "domain_audit_events", id=row["audit_event_id"])
        outbox = _one(capture, "outbox_events", event_id=row["outbox_event_id"])
        _scope(outbox, original.scope)
        metadata = {"plan_digest": plan["plan_digest"], "reason": row["reason"]}
        require(audit["actor_user_id"] == row["actor_id"] and audit["object_type"] == "operational_finance"
                and audit["object_id"] == plan["id"] and audit["action"] == action and audit["metadata_json"] == metadata
                and outbox["aggregate_type"] == "operational_finance" and outbox["aggregate_id"] == plan["id"]
                and outbox["event_type"] == action and outbox["payload"] == {**metadata, "audit_event_id": audit["id"]})
    for table in ("customer_partial_return_monetary_entries", "customer_partial_return_monetary_restorations", "customer_partial_return_monetary_commands"):
        for row in capture.rows(table):
            _scope(row, original.scope)
            plan = _one(capture, "customer_partial_return_monetary_plans", id=row["plan_id"])
            if table.endswith("_commands"):
                intent = row["request_json"]
                require(set(intent) == {"protocol_version", "operation", "actor_id", "request"}
                        and type(intent["protocol_version"]) is int and intent["protocol_version"] == 3
                        and intent["operation"] == row["operation"] and intent["actor_id"] == row["actor_id"]
                        and type(intent["request"]) is dict and row["request_digest"] == _digest(intent)
                        and row["response_json"]["id"] == plan["id"] and row["response_json"]["plan_digest"] == plan["plan_digest"])


def _immutable_transition(before: Capture, after: Capture) -> None:
    """Append-only rows and already posted headers stay byte-for-byte original."""
    old, new = dict(before.raw_tables), dict(after.raw_tables)
    fixed = ("finance_posting_effects", "finance_entry_lines", "finance_entry_line_dimensions", "inventory_layer_consumptions", "operational_fx_sources",
             "operational_fx_reviews", "operational_fx_links", "operational_fx_commands", "customer_partial_return_monetary_history",
             "customer_partial_return_monetary_restorations", "customer_partial_return_monetary_events", "customer_partial_return_monetary_commands")
    for name in fixed:
        require(set(old[name]) <= set(new[name]))
    for effect in before.rows("finance_posting_effects"):
        require(_one(before, "finance_entries", id=effect["entry_id"]) == _one(after, "finance_entries", id=effect["entry_id"]))
    for table in ("operational_fx_plans", "customer_partial_return_monetary_plans"):
        for plan in before.rows(table):
            if plan["phase"] in {2, 3}:
                require(plan == _one(after, table, id=plan["id"]))
                if table == "customer_partial_return_monetary_plans":
                    require([row for row in before.rows("customer_partial_return_monetary_entries") if row["plan_id"] == plan["id"]]
                            == [row for row in after.rows("customer_partial_return_monetary_entries") if row["plan_id"] == plan["id"]])
    for layer in before.rows("inventory_cost_layers"):
        current = _one(after, "inventory_cost_layers", id=layer["id"])
        mutable = {"remaining_quantity_scaled", "remaining_value_minor", "updated_at", "row_version"}
        require({key: value for key, value in layer.items() if key not in mutable} == {key: value for key, value in current.items() if key not in mutable})


def qualify_raw_cycle(packet: RawPacket) -> dict[str, Any]:
    """Closed raw financial trace, with no current-authority or browser claim."""
    first = next((index for index, capture in enumerate(packet.captures) if capture.rows("stock_sales_monetary_origins")), None)
    require(first in {0, 2})
    first = cast(int, first)
    original = verify_original_rows(packet.captures[first], source_order_id=packet.source_order_id)
    initial_stock = _one(packet.captures[0], "stock_sales_orders", id=packet.source_order_id)
    if first == 2:
        require(initial_stock["status"] == "Draft" and _one(packet.captures[1], "stock_sales_orders", id=packet.source_order_id)["status"] == "Delivered")
        for capture in packet.captures[:first]:
            require(not capture.rows("stock_sales_monetary_origins") and all(not capture.rows(name) for name in MONETARY_COLUMNS if name != "stock_sales_monetary_origins")
                    and all(not capture.rows("operational_fx_" + name) for name in ("sources", "plans", "reviews", "links", "commands")))
    prior_audit: tuple[str, ...] = ()
    final_events: tuple[dict[str, Any], ...] = ()
    final_totals = (0, 0, 0)
    immutable_source = _one(packet.captures[first], "stock_sales_monetary_origins", id=original.origin_id)
    for index, capture in enumerate(packet.captures):
        chain = _audit_chain(capture, packet.tenant_id)
        require(chain[:len(prior_audit)] == prior_audit)
        prior_audit = chain
        if index:
            _immutable_transition(packet.captures[index - 1], capture)
        stock = _one(capture, "stock_sales_orders", id=packet.source_order_id)
        require(all(stock[key] == initial_stock[key] for key in ("tenant_id", "workspace_id", "organization_id", "legal_entity_id", "item_id", "uom_id", "location_id", "quantity_scaled", "quantity_precision", "source", "source_digest")))
        if index < first:
            continue
        check = verify_original_rows(capture, source_order_id=packet.source_order_id)
        require(check.fingerprint == original.fingerprint)
        retained = _one(capture, "stock_sales_monetary_origins", id=original.origin_id)
        require({key: value for key, value in retained.items() if key != "ar_balance"} == {key: value for key, value in immutable_source.items() if key != "ar_balance"})
        final_events = verify_history_rows(capture, original)
        posted = verify_posted_journal_rows(capture, original, final_events)
        verify_physical_rows(capture, original, final_events)
        closing, active = verify_valuation_rows(capture, original, final_events)
        _projection(capture, original, final_events, active)
        _native_memberships(capture, original)
        allowed = _receipt_effects(capture, original) | set(posted) | set(closing)
        allowed.add(stock["cogs_effect_id"])
        recognition = _one(capture, "operational_fx_links", plan_id=stock["invoice_plan_id"])
        allowed.add(recognition["posting_effect_id"])
        final_totals = _ledger(capture, original, allowed)
        if index == len(packet.captures) - 1:
            require(active is None)
    require(bool(final_events))
    terminal = final_events[-1]["after"]
    require(terminal["remaining_quantity_scaled"] == terminal["transaction_outstanding_minor"] == terminal["functional_outstanding_minor"]
            == terminal["transaction_refund_due_minor"] == terminal["functional_refund_due_minor"] == 0)
    return {"schema_version": "independent-monetary-posted-cycle-proof-v1", "status": "passed",
            "case": "identity" if original.source["transaction_policy"]["currency_code"] == original.source["functional_policy"]["currency_code"] else "foreign",
            "captures": len(packet.captures), "tables": 91, "monetary_events": len(final_events),
            "final_posting_effects": final_totals[0], "final_posted_lines": final_totals[1], "final_debits_minor": str(final_totals[2]), "final_credits_minor": str(final_totals[2]),
            "zero_financial_entries_omitted": True, "original_rows_immutable": True, "active_prefix_witnesses": True,
            "posted_journals_bound": True, "physical_restorations_bound": True, "closing_valuations_bound": True,
            "audit_chain_valid": True, "audit_original_prefix_equal": True, "observations": 0, "observation_business_tables": 89,
            "observation_business_original_rows_equal": False, "observation_audit_actions_bound": False, "observation_chronology_bound": False,
            "populated_restore_original_rows_equal": False, "restored_tables": 0, "restored_rows": 0,
            "current_authorization_proven": False, "input_sha256": packet.sha256}


OBSERVATIONS_SCHEMA = "customer-partial-return-monetary-posted-observations-input-v1"
OBSERVATION_SCHEMA = "customer-partial-return-monetary-browser-observation-v1"
RESTORE_SCHEMA = "customer-partial-return-monetary-posted-restored-input-v1"
_OBSERVATION_FIELDS = {"schema_version", "kind", "tenant_id", "source_order_id", "capture", "history_version", "plan_id", "plan_digest", "tables", "refusal"}
_SCOPE_CODES = {"entity_scope_denied", "organization_scope_denied", "workspace_scope_denied", "tenant_scope_denied"}


def verify_observations(packet: RawPacket, proof: dict[str, Any], original: bytes) -> Capture:
    """Join manual replay/refusals/final read to economic originals in order.

    HTTP receipts are bounded observed metadata. Current authorization remains
    outside this offline proof. The separate refused-request body is pinned by
    the browser custody adapter; it is not an input to financial arithmetic.
    """
    value = _decode(original)
    require(type(value) is dict and set(value) == {"schema_version", "tenant_id", "source_order_id", "observations"}
            and value["schema_version"] == OBSERVATIONS_SCHEMA and value["tenant_id"] == packet.tenant_id and value["source_order_id"] == packet.source_order_id)
    foreign = proof["case"] == "foreign"
    versions = (0, 0, 0, 1, 2, 2, 2, 3, 4, 5, 6, 7) if foreign else (0, 0, 0, 1, 2, 3, 4, 5, 6, 7)
    require(len(packet.captures) == len(versions) and all(len(capture.rows("customer_partial_return_monetary_history")) == version for capture, version in zip(packet.captures, versions, strict=True)))
    kinds: tuple[tuple[str, int], ...] = (("ActiveValuationRefusal", 5),) if foreign else ()
    kinds += (("RetainedReplay", len(versions) - 3), ("ScopeRefusal", len(versions) - 1), ("FinalRead", len(versions) - 1))
    require(type(value["observations"]) is list and len(value["observations"]) == len(kinds))
    previous: Capture | None = None
    previous_index: int | None = None
    for row, (kind, index) in zip(value["observations"], kinds, strict=True):
        require(type(row) is dict and set(row) == _OBSERVATION_FIELDS and row["schema_version"] == OBSERVATION_SCHEMA
                and row["kind"] == kind and row["tenant_id"] == packet.tenant_id and row["source_order_id"] == packet.source_order_id
                and type(row["capture"]) is int and row["capture"] == index and type(row["history_version"]) is int and row["history_version"] == versions[index])
        observation = decode_capture({"capture": index, "tables": row["tables"]}, index=index, tenant_id=packet.tenant_id)
        baseline = previous if previous_index == index else packet.captures[index]
        baseline = cast(Capture, baseline)
        transition = verify_audit_only_transition({name: list(rows) for name, rows in baseline.raw_tables}, row["tables"], tenant_id=packet.tenant_id, scope_refusal=kind == "ScopeRefusal")
        if kind in {"ActiveValuationRefusal", "RetainedReplay"}:
            _hex(row["plan_digest"])
            if kind == "RetainedReplay":
                plan = _one(observation, "customer_partial_return_monetary_plans", id=row["plan_id"])
                history = _one(observation, "customer_partial_return_monetary_history", sequence=5)
                require(history["partial_plan_id"] == plan["id"] and plan["phase"] == 2 and plan["operation"] == "Refund" and plan["plan_digest"] == row["plan_digest"])
            else:
                plan = _one(observation, "operational_fx_plans", id=row["plan_id"])
                require(plan["phase"] == 2 and plan["kind"] == "revalue" and plan["payload"]["plan_digest"] == row["plan_digest"])
                source = verify_original_rows(observation, source_order_id=packet.source_order_id)
                events = verify_history_rows(observation, source)
                _effects, active = verify_valuation_rows(observation, source, events)
                require(active == plan["id"])
            require(transition["appended_audit_events"] > 0)
        else:
            require(row["plan_id"] is None and row["plan_digest"] is None)
        if kind in {"ScopeRefusal", "ActiveValuationRefusal"}:
            refusal = row["refusal"]
            require(type(refusal) is dict and set(refusal) == {"operation", "status", "code"} and type(refusal["status"]) is int)
            if kind == "ScopeRefusal":
                require(refusal["operation"] == "ReadSource" and refusal["status"] == 403 and refusal["code"] in _SCOPE_CODES)
                old = _audit_chain(baseline, packet.tenant_id)
                added = [_decode(raw) for raw in _audit_chain(observation, packet.tenant_id)[len(old):]]
                require(any(event["metadata_json"]["policy_decision_evidence"]["allowed"] is False
                            and event["metadata_json"]["policy_decision_evidence"]["reason_code"] == refusal["code"] for event in added))
            else:
                require(refusal == {"operation": "PrepareReturn", "status": 409, "code": "monetary_return_state_conflict"})
        else:
            require(row["refusal"] is None)
        if index + 1 < len(packet.captures):
            observed_chain = _audit_chain(observation, packet.tenant_id)
            following = _audit_chain(packet.captures[index + 1], packet.tenant_id)
            require(following[:len(observed_chain)] == observed_chain)
        previous, previous_index = observation, index
    require(previous is not None)
    proof.update(observations=len(kinds), observation_business_original_rows_equal=True, observation_audit_actions_bound=True, observation_chronology_bound=True)
    return cast(Capture, previous)


def verify_restore(packet: RawPacket, final: Capture, original: bytes, proof: dict[str, Any]) -> None:
    value = _decode(original)
    require(type(value) is dict and set(value) == {"schema_version", "tenant_id", "source_order_id", "tables"}
            and value["schema_version"] == RESTORE_SCHEMA and value["tenant_id"] == packet.tenant_id and value["source_order_id"] == packet.source_order_id)
    restored = decode_capture({"capture": final.index, "tables": value["tables"]}, index=final.index, tenant_id=packet.tenant_id)
    require(restored.raw_tables == final.raw_tables)
    proof.update(populated_restore_original_rows_equal=True, restored_tables=91, restored_rows=sum(len(rows) for _, rows in restored.raw_tables))


def qualify_files(input_path: Path, *, observations_path: Path | None = None, restore_path: Path | None = None) -> dict[str, Any]:
    """Read originals twice; never replace source custody with caller totals."""
    sources = {path: read_original(path) for path in (input_path, observations_path, restore_path) if path is not None}
    require(len(sources) == 1 + (observations_path is not None) + (restore_path is not None))
    source_path = Path(__file__).absolute()
    source = read_original(source_path)
    packet = decode_packet(sources[input_path])
    proof = qualify_raw_cycle(packet)
    final = packet.captures[-1]
    if observations_path is not None:
        final = verify_observations(packet, proof, sources[observations_path])
    if restore_path is not None:
        verify_restore(packet, final, sources[restore_path], proof)
    proof.update(observations_input_sha256=hashlib.sha256(sources[observations_path]).hexdigest() if observations_path is not None else None,
                 restore_input_sha256=hashlib.sha256(sources[restore_path]).hexdigest() if restore_path is not None else None,
                 oracle_source_sha256=hashlib.sha256(source).hexdigest())
    for path, original in sources.items():
        require_original_unchanged(path, original)
    require_original_unchanged(source_path, source)
    return proof


def _write_new(path: Path, proof: dict[str, Any]) -> None:
    require(path.is_absolute() and ".." not in path.parts and not path.exists())
    for candidate in (*reversed(path.parent.parents), path.parent):
        info = candidate.lstat()
        require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400)
    original = (_audit_json(proof) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    require(read_original(path) == original)


def main() -> int:
    parser = argparse.ArgumentParser(description="Independently verify private monetary original rows.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--observations-input", type=Path)
    parser.add_argument("--restore-input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        proof = qualify_files(args.input, observations_path=args.observations_input, restore_path=args.restore_input)
        _write_new(args.output, proof)
    except (MonetaryRawRefusal, OSError, ValueError, TypeError, KeyError, IndexError, OverflowError):
        parser.exit(2, "Independent monetary raw input refused.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
