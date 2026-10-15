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
    require(type(precision) is int and 0 <= precision <= 6 and source["quantity_precision"] == precision
            and source["quantity_scaled"] == quantity and declared["quantity_scaled"] == quantity
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
        require(retained == {**tax, "foreign_tax_minor": cut, "functional_tax_minor": functional_cut})
        components.append((cut, functional_cut))
        functional_gross = converted
    require((_minor(invoice["subtotal_minor"]), _minor(invoice["tax_minor"]), _minor(invoice["total_minor"])) == (net, gross - net, gross)
            and _minor(line["tax_minor"]) == gross - net
            and [equation[key] for key in ("foreign_net_minor", "foreign_tax_minor", "foreign_gross_minor", "functional_net_minor", "functional_gross_minor")]
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
    revenue = _effect(capture, link["posting_effect_id"], scope=scope, policy=_full_policy(local), expected=expected, external_reference=recognition["id"])
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
                             external_reference=plan["id"], expected_dimensions=dimensions)
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
