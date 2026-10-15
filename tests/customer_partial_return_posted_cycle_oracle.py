"""Independent exact expectations for an actual partial-return posted cycle.

No application imports or implementation-generated financial expectations.
The native row adapter must separately bind these expectations to original SQL
rows, posted effects and populated restore. Arithmetic alone is not native proof.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Literal, cast

MAX_MINOR = 9_000_000_000_000_000_000
MAX_EVENTS = 256
TABLES = (
    'ar_customers',
    'ar_idempotency_keys',
    'ar_invoice_lines',
    'ar_invoices',
    'ar_receipt_allocations',
    'ar_receipts',
    'commercial_collection_cancellations',
    'commercial_collection_commands',
    'commercial_collection_links',
    'commercial_collection_plans',
    'commercial_collection_reviews',
    'customer_partial_return_commands',
    'customer_partial_return_events',
    'customer_partial_return_history',
    'customer_partial_return_plans',
    'customer_partial_return_restorations',
    'customer_partial_return_sources',
    'customer_return_commands',
    'customer_return_events',
    'customer_return_plans',
    'domain_audit_events',
    'domain_audit_ledger_state',
    'finance_accounts',
    'finance_charts',
    'finance_dimension_values',
    'finance_dimensions',
    'finance_entries',
    'finance_entry_line_dimensions',
    'finance_entry_lines',
    'finance_journals',
    'finance_posting_commands',
    'finance_posting_effects',
    'inventory_cost_layers',
    'inventory_count_lines',
    'inventory_count_sessions',
    'inventory_items',
    'inventory_layer_consumptions',
    'inventory_locations',
    'inventory_lots',
    'inventory_movement_lines',
    'inventory_movements',
    'inventory_quantity_claim_gates',
    'inventory_quantity_source_guards',
    'inventory_quantity_source_releases',
    'inventory_receipt_commands',
    'inventory_receipt_links',
    'inventory_receipt_plans',
    'inventory_receipt_reviews',
    'inventory_reorder_rules',
    'inventory_transfer_claims',
    'inventory_transfer_commands',
    'inventory_transfer_events',
    'inventory_transfer_releases',
    'inventory_transfer_sources',
    'inventory_units_of_measure',
    'inventory_valuation_documents',
    'inventory_valuation_input_costs',
    'inventory_valuation_lines',
    'inventory_valuation_policies',
    'inventory_valuation_reversal_effects',
    'inventory_valuation_reversals',
    'inventory_warehouses',
    'operational_finance_commands',
    'operational_finance_links',
    'operational_finance_plans',
    'operational_finance_reviews',
    'outbox_consumer_receipts',
    'outbox_delivery_evidence',
    'outbox_events',
    'stock_commerce_commands',
    'stock_commerce_lines',
    'stock_commerce_orders',
    'stock_commerce_tranches',
    'stock_sales_commands',
    'stock_sales_events',
    'stock_sales_issue_claims',
    'stock_sales_orders',
    'stock_sales_reservations',
)


class CycleRefusal(ValueError):
    """A constant failure never includes a private financial value."""


def require(value: bool) -> None:
    if not value:
        raise CycleRefusal("Independent partial-return cycle refused.")


def integer(value: object, *, positive: bool = False) -> int:
    require(type(value) is int)
    number = cast(int, value)
    require(0 <= number <= MAX_MINOR and (not positive or number > 0))
    return number


def identity(value: object) -> str:
    require(type(value) is str)
    token = cast(str, value)
    require(0 < len(token) <= 200 and token == token.strip())
    return token


def exact_minor(value: Fraction) -> int:
    require(type(value) is Fraction and value.denominator == 1)
    return integer(value.numerator, positive=True)


@dataclass(frozen=True, slots=True)
class Consumption:
    position: int
    consumption_id: str
    layer_id: str
    quantity_scaled: int
    value_minor: int

    def __post_init__(self) -> None:
        integer(self.position, positive=True)
        identity(self.consumption_id)
        identity(self.layer_id)
        integer(self.quantity_scaled, positive=True)
        integer(self.value_minor, positive=True)


@dataclass(frozen=True, slots=True)
class OriginalSale:
    quantity_precision: int
    quantity_scaled: int
    gross_minor: int
    initial_collected_minor: int
    currency_code: str
    currency_precision: int
    consumptions: tuple[Consumption, ...]

    def __post_init__(self) -> None:
        integer(self.quantity_precision)
        integer(self.currency_precision)
        require(self.quantity_precision <= 6 and self.currency_precision <= 8)
        integer(self.quantity_scaled, positive=True)
        integer(self.gross_minor, positive=True)
        integer(self.initial_collected_minor)
        require(self.initial_collected_minor <= self.gross_minor)
        identity(self.currency_code)
        require(type(self.consumptions) is tuple and 1 <= len(self.consumptions) <= 32)
        seen: set[str] = set()
        layers: set[str] = set()
        for number, row in enumerate(self.consumptions, 1):
            require(type(row) is Consumption)
            row.__post_init__()
            require(row.position == number and row.consumption_id not in seen and row.layer_id not in layers)
            seen.add(row.consumption_id)
            layers.add(row.layer_id)
        require(sum(row.quantity_scaled for row in self.consumptions) == self.quantity_scaled)
        integer(sum(row.value_minor for row in self.consumptions), positive=True)


@dataclass(frozen=True, slots=True)
class Portion:
    position: int
    consumption_id: str
    layer_id: str
    offset_quantity_scaled: int
    quantity_scaled: int
    value_minor: int


Kind = Literal["Return", "Collection", "Refund", "ReverseReturn", "ReverseRefund", "ReverseCollection"]


@dataclass(frozen=True, slots=True)
class Event:
    event_id: str
    kind: Kind
    expected_history_version: int
    quantity_scaled: int = 0
    amount_minor: int = 0
    original_event_id: str | None = None

    def __post_init__(self) -> None:
        identity(self.event_id)
        integer(self.expected_history_version)
        integer(self.quantity_scaled)
        integer(self.amount_minor)
        require(self.kind in {"Return", "Collection", "Refund", "ReverseReturn", "ReverseRefund", "ReverseCollection"})
        if self.kind == "Return":
            require(self.quantity_scaled > 0 and self.amount_minor == 0 and self.original_event_id is None)
        elif self.kind in {"Collection", "Refund"}:
            require(self.quantity_scaled == 0 and self.amount_minor > 0 and self.original_event_id is None)
        else:
            require(self.quantity_scaled == self.amount_minor == 0)
            identity(self.original_event_id)


@dataclass(frozen=True, slots=True)
class ExpectedEffect:
    event: Event
    portions: tuple[Portion, ...]
    account_deltas: tuple[tuple[str, int], ...]
    returned_quantity_scaled: int
    total_credit_minor: int
    total_collections_minor: int
    total_refunds_minor: int
    receivable_minor: int
    refund_liability_minor: int


def prefix_portions(source: OriginalSale, start: int, quantity: int) -> tuple[Portion, ...]:
    source.__post_init__()
    integer(start)
    integer(quantity, positive=True)
    require(start + quantity <= source.quantity_scaled)
    stop = start + quantity
    cursor = 0
    result = []
    for row in source.consumptions:
        left, right = max(start, cursor), min(stop, cursor + row.quantity_scaled)
        if right > left:
            selected = right - left
            value = exact_minor(Fraction(row.value_minor * selected, row.quantity_scaled))
            result.append(Portion(row.position, row.consumption_id, row.layer_id, left - cursor, selected, value))
        cursor += row.quantity_scaled
    require(sum(row.quantity_scaled for row in result) == quantity)
    return tuple(result)


def residuals(source: OriginalSale, quantity: int, collections: int, refunds: int) -> tuple[int, int, int]:
    integer(quantity)
    integer(collections)
    integer(refunds)
    require(quantity <= source.quantity_scaled)
    credit_fraction = Fraction(source.gross_minor * quantity, source.quantity_scaled)
    credit = exact_minor(credit_fraction) if quantity else 0
    receivable = max(source.gross_minor - credit - collections, 0)
    entitlement = max(credit + collections - source.gross_minor, 0)
    require(refunds <= entitlement)
    return credit, receivable, entitlement - refunds


def expected_cycle(source: OriginalSale, events: tuple[Event, ...]) -> tuple[ExpectedEffect, ...]:
    """Compute independent event effects; require native rows elsewhere."""
    source.__post_init__()
    require(type(events) is tuple and 0 < len(events) <= MAX_EVENTS)
    quantity, collections, refunds = 0, source.initial_collected_minor, 0
    active: list[ExpectedEffect] = []
    seen: set[str] = set()
    result = []
    for version, event in enumerate(events):
        require(type(event) is Event)
        event.__post_init__()
        require(event.expected_history_version == version and event.event_id not in seen)
        seen.add(event.event_id)
        _before_credit, before_ar, before_liability = residuals(source, quantity, collections, refunds)
        portions: tuple[Portion, ...] = ()
        deltas: Counter[str] = Counter()
        inverse = event.kind.startswith("Reverse")
        if event.kind == "Return":
            portions = prefix_portions(source, quantity, event.quantity_scaled)
            credit = exact_minor(Fraction(source.gross_minor * event.quantity_scaled, source.quantity_scaled))
            cost = sum(row.value_minor for row in portions)
            quantity += event.quantity_scaled
            ar_release = min(before_ar, credit)
            deltas.update({"REVENUE": credit, "AR": -ar_release, "REFUND": -(credit - ar_release),
                           "INVENTORY": cost, "COGS": -cost})
        elif event.kind == "Collection":
            require(event.amount_minor <= before_ar)
            collections += event.amount_minor
            deltas.update({"CASH": event.amount_minor, "AR": -event.amount_minor})
        elif event.kind == "Refund":
            require(event.amount_minor <= before_liability)
            refunds += event.amount_minor
            deltas.update({"REFUND": event.amount_minor, "CASH": -event.amount_minor})
        else:
            require(bool(active) and active[-1].event.event_id == event.original_event_id)
            target = active.pop()
            require(event.kind == "Reverse" + target.event.kind)
            if target.event.kind == "Return":
                quantity -= target.event.quantity_scaled
                portions = target.portions
            elif target.event.kind == "Collection":
                collections -= target.event.amount_minor
            else:
                refunds -= target.event.amount_minor
            deltas.update({account: -amount for account, amount in target.account_deltas})
        credit_after, ar_after, liability_after = residuals(source, quantity, collections, refunds)
        require(sum(deltas.values()) == 0 and credit_after >= 0)
        require(deltas["AR"] == ar_after - before_ar)
        require(deltas["REFUND"] == before_liability - liability_after)
        effect = ExpectedEffect(event, portions, tuple(sorted((account, amount) for account, amount in deltas.items() if amount)),
                                quantity, credit_after, collections, refunds, ar_after, liability_after)
        if not inverse:
            active.append(effect)
        result.append(effect)
    return tuple(result)


def row_index(rows: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
    require(type(rows) is tuple and len(rows) <= 1024)
    result = {}
    for row in rows:
        require(type(row) is dict)
        key = identity(row.get("id"))
        require(key not in result)
        result[key] = row
    return result


def verify_posted_gl_amount_delta(
    source: OriginalSale,
    expected: ExpectedEffect,
    before: dict[str, tuple[dict[str, Any], ...]],
    after: dict[str, tuple[dict[str, Any], ...]],
    account_roles: dict[str, str],
) -> dict[str, Any]:
    """Bind expected deltas to real posting-effect/entry/line row membership.

    This rejects unposted templates, missing/orphan/extra effects, alteration of
    any previously posted row, and balanced extra or offsetting entry lines.
    Native owner, snapshots, dimensions, physical/history and custody checks
    remain separate requirements; this function proves only the stated GL delta.
    """
    source.__post_init__()
    names = {"finance_posting_effects", "finance_entries", "finance_entry_lines"}
    require(type(before) is dict and type(after) is dict and set(before) == set(after) == names)
    require(type(expected) is ExpectedEffect and type(account_roles) is dict
            and set(account_roles) == {"AR", "REVENUE", "INVENTORY", "COGS", "REFUND", "CASH"})
    for account_id in account_roles.values():
        identity(account_id)
    require(len(set(account_roles.values())) == len(account_roles))
    roles = {account_id: role for role, account_id in account_roles.items()}
    old, new = ({name: row_index(tables[name]) for name in names} for tables in (before, after))
    old_entries = {identity(row.get("entry_id")) for row in old["finance_posting_effects"].values()}
    require(len(old_entries) == len(old["finance_posting_effects"]))
    for effect_id, row in old["finance_posting_effects"].items():
        require(new["finance_posting_effects"].get(effect_id) == row)
    for entry_id in old_entries:
        require(entry_id in old["finance_entries"] and new["finance_entries"].get(entry_id) == old["finance_entries"][entry_id])
    for line_id, row in old["finance_entry_lines"].items():
        if row.get("entry_id") in old_entries:
            require(new["finance_entry_lines"].get(line_id) == row)
    require({key for key, row in old["finance_entry_lines"].items() if row.get("entry_id") in old_entries}
            == {key for key, row in new["finance_entry_lines"].items() if row.get("entry_id") in old_entries})
    added = set(new["finance_posting_effects"]) - set(old["finance_posting_effects"])
    expected_count = 2 if expected.event.kind in {"Return", "ReverseReturn"} else 1
    require(len(added) == expected_count)
    entries = {identity(new["finance_posting_effects"][key].get("entry_id")) for key in added}
    require(len(entries) == expected_count and not entries.intersection(old_entries))
    lines = [row for row in new["finance_entry_lines"].values() if row.get("entry_id") in entries]
    require(len(lines) == len(expected.account_deltas))
    seen_roles: set[str] = set()
    delta: Counter[str] = Counter()
    for entry_id in entries:
        require(entry_id in new["finance_entries"])
        header = new["finance_entries"][entry_id]
        require(header.get("status") == "Validated" and header.get("currency_code") == source.currency_code
                and integer(header.get("currency_precision")) == source.currency_precision)
        entry_lines = sorted((row for row in lines if row.get("entry_id") == entry_id),
                             key=lambda row: integer(row.get("line_number"), positive=True))
        require([integer(row.get("line_number")) for row in entry_lines] == list(range(1, len(entry_lines) + 1)))
        total_debit = total_credit = 0
        for row in entry_lines:
            role = roles.get(identity(row.get("account_id")))
            require(role is not None and role not in seen_roles)
            seen_roles.add(cast(str, role))
            debit, credit = integer(row.get("debit_minor")), integer(row.get("credit_minor"))
            require((debit > 0) != (credit > 0))
            total_debit += debit
            total_credit += credit
            delta[cast(str, role)] += debit - credit
        require(total_debit == total_credit == integer(header.get("total_debit_minor"), positive=True)
                == integer(header.get("total_credit_minor"), positive=True))
    require(tuple(sorted(delta.items())) == expected.account_deltas)
    return {"posting_effects": len(added), "posted_entries": len(entries), "posted_lines": len(lines),
            "exact_account_minor_deltas_equal": True, "previously_posted_rows_unchanged": True,
            "unposted_proposal_accepted_as_posting": False,
            "scope": "GL amount and membership only; native owner/history/physical/authority/restore/custody must also be verified."}


def decode_row(text: str, *, maximum_bytes: int = 4 * 1024 * 1024) -> dict[str, Any]:
    """Decode original PostgreSQL to_jsonb text without binary float coercion."""
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            require(key not in result)
            result[key] = value
        return result

    def nonfinite(_value: str) -> Any:
        raise CycleRefusal("Independent native row refused.")

    def exact_fraction(token: str) -> Fraction:
        require(len(token) <= 80 and re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]{1,2})?", token) is not None)
        value = Fraction(token)
        require(value.numerator.bit_length() <= 512 and value.denominator.bit_length() <= 512)
        return value

    def exact_integer(token: str) -> int:
        require(len(token) <= 20)
        return int(token)

    require(type(text) is str and len(text.encode("utf-8")) <= maximum_bytes)
    try:
        row = json.loads(text, parse_float=exact_fraction, parse_int=exact_integer, parse_constant=nonfinite, object_pairs_hook=pairs)
    except (ValueError, RecursionError) as exc:
        raise CycleRefusal("Independent native row refused.") from exc
    require(type(row) is dict)
    return cast(dict[str, Any], row)


def posted_ledger_totals(source: OriginalSale, tables: dict[str, tuple[dict[str, Any], ...]]) -> dict[str, Any]:
    """Count and sum only actual effect-linked entries, excluding void/drafts."""
    effects = row_index(tables["finance_posting_effects"])
    entries = row_index(tables["finance_entries"])
    lines = row_index(tables["finance_entry_lines"])
    accounts = row_index(tables["finance_accounts"])
    posted = {identity(row["entry_id"]) for row in effects.values()}
    require(bool(posted) and len(posted) == len(effects) and posted <= set(entries))
    balances: Counter[str] = Counter()
    debit_sum = credit_sum = line_count = 0
    for identifier in posted:
        entry = entries[identifier]
        require(entry["status"] == "Validated" and entry["currency_code"] == source.currency_code
                and integer(entry["currency_precision"]) == source.currency_precision)
        selected = sorted((row for row in lines.values() if row["entry_id"] == identifier),
                          key=lambda row: integer(row["line_number"], positive=True))
        require(len(selected) >= 2 and [row["line_number"] for row in selected] == list(range(1, len(selected) + 1)))
        debit = credit = 0
        for row in selected:
            account = accounts.get(identity(row["account_id"]))
            require(account is not None)
            code = identity(cast(dict[str, Any], account)["account_code"])
            left, right = integer(row["debit_minor"]), integer(row["credit_minor"])
            require((left > 0) != (right > 0))
            debit += left
            credit += right
            balances[code] += left - right
        require(debit == credit == integer(entry["total_debit_minor"], positive=True) == integer(entry["total_credit_minor"], positive=True))
        debit_sum += debit
        credit_sum += credit
        line_count += len(selected)
    require(debit_sum == credit_sum and sum(balances.values()) == 0)
    return {"final_actual_posting_effects": len(effects), "final_actual_posted_entries": len(posted), "final_actual_posted_lines": line_count,
            "final_total_debit_minor": debit_sum, "final_total_credit_minor": credit_sum,
            "final_account_minor_balances": dict(sorted(balances.items())), "unposted_or_void_entries_excluded": True}


def qualify_raw_cycle(packet: dict[str, Any]) -> dict[str, Any]:
    """Read actual original SQL captures, independently deriving event amounts.

    This finite reader proves incremental GL/FIFO/layer/history equations. It
    does not prove RLS, authority, three-actor governance, recovery or API behavior.
    Those are separate native tests and final acceptance requirements.
    """
    require(type(packet) is dict and set(packet) == {"schema_version", "tenant_id", "source_order_id", "captures"})
    require(packet["schema_version"] == "customer-partial-return-posted-cycle-input-v1")
    tenant, order_id = identity(packet["tenant_id"]), identity(packet["source_order_id"])
    captures = packet["captures"]
    require(type(captures) in {tuple, list} and 2 <= len(captures) <= MAX_EVENTS + 1)
    decoded = []
    mandatory = {"stock_sales_orders", "ar_invoices", "ar_receipt_allocations", "inventory_layer_consumptions",
                 "finance_accounts", "finance_posting_effects", "finance_entries", "finance_entry_lines", "inventory_cost_layers",
                 "customer_partial_return_history", "customer_partial_return_plans", "customer_partial_return_restorations",
                 "inventory_movements", "inventory_movement_lines"}
    table_set = set(captures[0])
    require(mandatory <= table_set and table_set == set(TABLES))
    for capture in captures:
        require(type(capture) is dict and set(capture) == table_set)
        tables = {}
        for name, originals in capture.items():
            require(type(name) is str and type(originals) in {tuple, list} and len(originals) <= 4096)
            require(len(originals) == len(set(originals)))
            tables[name] = tuple(decode_row(raw) for raw in originals)
            require(all(row.get("tenant_id") == tenant for row in tables[name]))
        decoded.append(tables)
    first = decoded[0]
    require(not first["customer_partial_return_history"])
    stock = row_index(first["stock_sales_orders"])[order_id]
    invoice = row_index(first["ar_invoices"])[identity(stock.get("invoice_id"))]
    consumptions = first["inventory_layer_consumptions"]
    selected = []
    for position, allocation in enumerate(stock["issue_plan"]["allocations"], 1):
        original = [row for row in consumptions if row["cost_layer_id"] == allocation["cost_layer_id"]]
        require(len(original) == 1)
        row = original[0]
        selected.append(Consumption(position, row["id"], row["cost_layer_id"], row["quantity_scaled"], row["value_minor"]))
    collected = sum(integer(row["amount_minor"], positive=True) for row in first["ar_receipt_allocations"] if row["invoice_id"] == invoice["id"])
    source = OriginalSale(stock["quantity_precision"], stock["quantity_scaled"], invoice["total_minor"], collected,
                          invoice["currency_code"], invoice["currency_precision"], tuple(selected))
    accounts = [row for row in first["finance_accounts"] if row["account_code"] in {"AR", "REVENUE", "INVENTORY", "COGS", "REFUND", "CASH"}]
    roles = {row["account_code"]: row["id"] for row in accounts}
    require(len(accounts) == len(roles) == 6)
    events: list[Event] = []
    original_history: tuple[dict[str, Any], ...] = ()
    effects_count = lines_count = 0
    for version, (before, after) in enumerate(zip(decoded, decoded[1:], strict=False)):
        require(after["inventory_layer_consumptions"] == consumptions)
        history = tuple(sorted(after["customer_partial_return_history"], key=lambda row: integer(row["sequence"], positive=True)))
        require(len(history) == version + 1 and history[:-1] == original_history and history[-1]["sequence"] == version + 1)
        current, plan = history[-1], None
        for field in ("quantity_scaled", "credit_minor", "cogs_minor", "amount_minor"):
            integer(current[field])
        if current["kind"] == "Collection":
            event = Event(identity(current["allocation_id"]), "Collection", version, amount_minor=current["amount_minor"])
        else:
            plan = row_index(after["customer_partial_return_plans"])[identity(current["plan_id"])]
            require(plan["phase"] == 2 and plan["source_order_id"] == order_id and plan["invoice_id"] == invoice["id"]
                    and plan["operation"] == current["kind"] and integer(plan["expected_history_version"]) == version)
            event = Event(plan["id"], plan["operation"], version,
                          quantity_scaled=plan["quantity_scaled"] if plan["operation"] == "Return" else 0,
                          amount_minor=plan["amount_minor"] if plan["operation"] == "Refund" else 0,
                          original_event_id=plan["original_id"] if plan["operation"].startswith("Reverse") else None)
        events.append(event)
        expected = expected_cycle(source, tuple(events))[-1]
        require(current["quantity_scaled"] == sum(row.quantity_scaled for row in expected.portions)
                and current["credit_minor"] == abs(dict(expected.account_deltas).get("REVENUE", 0))
                and current["cogs_minor"] == sum(row.value_minor for row in expected.portions))
        require(current["amount_minor"] == (abs(dict(expected.account_deltas).get("CASH", 0))
                                            if event.kind in {"Collection", "Refund", "ReverseRefund"} else 0))
        proof = verify_posted_gl_amount_delta(source, expected, {name: before[name] for name in (
            "finance_posting_effects", "finance_entries", "finance_entry_lines")}, {name: after[name] for name in (
            "finance_posting_effects", "finance_entries", "finance_entry_lines")}, roles)
        effects_count += proof["posting_effects"]
        lines_count += proof["posted_lines"]
        restorations = [row for row in after["customer_partial_return_restorations"] if plan is not None and row["plan_id"] == plan["id"]]
        require(len(restorations) == len(expected.portions))
        direction = -1 if event.kind == "ReverseReturn" else 1
        for portion in expected.portions:
            matching = [row for row in restorations if row["position"] == portion.position]
            require(len(matching) == 1)
            row = matching[0]
            for field in ("offset_quantity_scaled", "quantity_scaled", "value_minor"):
                integer(row[field], positive=field != "offset_quantity_scaled")
            require(type(row["direction"]) is int and row["direction"] in {-1, 1})
            require((row["original_consumption_id"], row["cost_layer_id"], row["offset_quantity_scaled"], row["quantity_scaled"], row["value_minor"], row["direction"])
                    == (portion.consumption_id, portion.layer_id, portion.offset_quantity_scaled, portion.quantity_scaled, portion.value_minor, direction))
        old_layers, new_layers = row_index(before["inventory_cost_layers"]), row_index(after["inventory_cost_layers"])
        require(set(old_layers) == set(new_layers))
        for key, old in old_layers.items():
            portions = [row for row in expected.portions if row.layer_id == key]
            for layer in (old, new_layers[key]):
                integer(layer["remaining_quantity_scaled"])
                integer(layer["remaining_value_minor"])
            require(new_layers[key]["remaining_quantity_scaled"] == old["remaining_quantity_scaled"] + direction * sum(row.quantity_scaled for row in portions)
                    and new_layers[key]["remaining_value_minor"] == old["remaining_value_minor"] + direction * sum(row.value_minor for row in portions))
        original_history = history
    final = expected_cycle(source, tuple(events))[-1]
    return {"schema_version": "customer-partial-return-posted-cycle-proof-v1", "captures": len(captures), "events": len(events),
            "new_actual_posting_effects": effects_count, "new_actual_posted_lines": lines_count,
            "returned_quantity_scaled": final.returned_quantity_scaled, "receivable_minor": final.receivable_minor,
            "refund_liability_minor": final.refund_liability_minor, "original_consumptions_unchanged": True,
            "incremental_gl_fifo_layer_history_equal": True, **posted_ledger_totals(source, decoded[-1]),
            "scope": "Incremental GL amounts, original FIFO portions, layer deltas and history only; authority, RLS, recovery and API need separate native qualification."}


AUDIT_TABLES = frozenset({"domain_audit_events", "domain_audit_ledger_state"})
AUDIT_FIELDS = frozenset({"tenant_id", "id", "sequence", "previous_hash", "event_hash", "actor_user_id", "actor_label",
                          "object_type", "object_id", "action", "before_hash", "after_hash", "metadata_json", "created_at"})
POLICY_FIELDS = frozenset({"actor_digest", "allowed", "context_binding", "context_digest", "decision_digest", "evaluator",
                           "granted_permission_digest", "policy_version", "principal_type", "reason_code", "request_id_digest",
                           "required_permission_digest", "schema_version", "scope_digest", "surface_digest"})
READ_PERMISSIONS = frozenset({"sales.read", "receivables.read", "inventory.read", "finance_core.read"})
POST_PERMISSIONS = READ_PERMISSIONS | {"sales.manage", "receivables.manage", "inventory.post", "inventory.valuation.approve",
                                       "finance_core.post", "finance_core.reverse"}


def audit_canonical(value: Any) -> str:
    """The documented v1 JSON wire grammar, independently implemented here."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise CycleRefusal("Independent audit originals refused.") from exc


def audit_digest(value: Any) -> str:
    return hashlib.sha256(audit_canonical(value).encode()).hexdigest()


def _text_digest(namespace: str, value: str) -> str:
    return audit_digest({"namespace": namespace, "value": value})


def _hex(value: Any) -> str:
    require(type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None)
    return cast(str, value)


def _capture_originals(value: Any, tenant_id: str) -> dict[str, tuple[str, ...]]:
    require(type(value) is dict and set(value) == set(TABLES))
    result = {}
    for name, rows in value.items():
        require(type(rows) in {list, tuple} and len(rows) <= 4096 and all(type(row) is str for row in rows))
        require(len(rows) == len(set(rows)))
        require(all(decode_row(row).get("tenant_id") == tenant_id for row in rows))
        result[name] = tuple(sorted(rows))
    return result


def _audit_chain(tables: dict[str, tuple[str, ...]], tenant_id: str) -> list[tuple[dict[str, Any], str]]:
    rows = sorted(((decode_row(raw), raw) for raw in tables["domain_audit_events"]),
                  key=lambda pair: integer(pair[0].get("sequence"), positive=True))
    previous = "0" * 64
    seen: set[str] = set()
    for sequence, (row, _raw) in enumerate(rows, 1):
        require(set(row) == AUDIT_FIELDS and row["tenant_id"] == tenant_id
                and integer(row["sequence"], positive=True) == sequence and row["previous_hash"] == previous)
        identifier = identity(row["id"])
        require(identifier not in seen)
        seen.add(identifier)
        for field in ("actor_label", "object_type", "object_id", "action", "created_at"):
            identity(row[field])
        require(row["actor_user_id"] is None or type(row["actor_user_id"]) is str)
        require(all(row[field] is None or type(row[field]) is str for field in ("before_hash", "after_hash")))
        require(type(row["metadata_json"]) is dict)
        unsigned = {key: row[key] for key in AUDIT_FIELDS - {"tenant_id", "event_hash"}}
        unsigned["metadata_json"] = audit_canonical(row["metadata_json"])
        previous = audit_digest(unsigned)
        require(_hex(row["event_hash"]) == previous)
    heads = tables["domain_audit_ledger_state"]
    require(len(heads) == 1 or not rows and not heads)
    if heads:
        head = decode_row(heads[0])
        require(set(head) == {"tenant_id", "last_sequence", "last_event_hash", "updated_at"}
                and head["tenant_id"] == tenant_id and integer(head["last_sequence"]) == len(rows)
                and _hex(head["last_event_hash"]) == previous)
        identity(head["updated_at"])
        require(not rows or head["updated_at"] == rows[-1][0]["created_at"])
    return rows


def _surface_contracts(tables: dict[str, tuple[str, ...]], post_plan_ids: set[str] | None = None) -> tuple[dict[str, frozenset[str]], set[str]]:
    plans = [decode_row(raw) for raw in tables["customer_partial_return_plans"]]
    orders = {identity(row["source_order_id"]) for row in plans}
    require(len(orders) == 1)
    actors = {identity(row["preparer_actor_id"]) for row in plans}
    actors.update(identity(decode_row(raw)["actor_id"]) for raw in tables["customer_partial_return_events"])
    surfaces: dict[str, frozenset[str]] = {
        "GET /api/v1/customer-partial-returns/plans": READ_PERMISSIONS,
        "GET /api/v1/customer-returns/plans": READ_PERMISSIONS,
        "server.scoped:finance_core.read": frozenset({"finance_core.read"}),
    }
    for order in orders:
        surfaces["GET /api/v1/customer-partial-returns/sources/" + order + "/balance"] = READ_PERMISSIONS
    for plan in plans:
        identifier = identity(plan["id"])
        surfaces["GET /api/v1/customer-partial-returns/plans/" + identifier] = READ_PERMISSIONS
        if plan["phase"] == 2 and (post_plan_ids is None or identifier in post_plan_ids):
            surfaces["POST /api/v1/customer-partial-returns/plans/" + identifier + "/post"] = POST_PERMISSIONS
    for suffix, permission in (("audit/events", "audit.read"), ("audit/verify", "audit.read"),
            ("security/overview", "security.center.read"), ("identity/users", "users.manage"),
            ("identity/sessions", "users.manage"), ("access/permissions", "roles.manage"), ("access/roles", "roles.manage"),
            ("security/integrations", "security.integrations.manage"), ("security/retention-policies", "security.retention.manage")):
        surfaces["GET /api/v1/admin/" + suffix] = frozenset({permission})
    return {_text_digest("audit.surface", surface): permissions for surface, permissions in surfaces.items()}, actors


def _policy_append(row: dict[str, Any], tables: dict[str, tuple[str, ...]], post_plan_ids: set[str] | None = None) -> None:
    require(row["actor_label"] == "policy-engine" and row["object_type"] == "authorization.policy_decision"
            and row["action"] == "evaluated" and row["before_hash"] is None)
    metadata = row["metadata_json"]
    require(set(metadata) == {"policy_decision_evidence", "request_id_digest"})
    policy = metadata["policy_decision_evidence"]
    require(type(policy) is dict and set(policy) == POLICY_FIELDS and type(policy["schema_version"]) is int
            and policy["schema_version"] == 1 and policy["policy_version"] == "central-policy-v3"
            and policy["allowed"] is True and policy["principal_type"] == "user" and policy["context_binding"] == "bound")
    for field in ("actor_digest", "context_digest", "decision_digest", "required_permission_digest", "scope_digest", "surface_digest", "request_id_digest", "granted_permission_digest"):
        _hex(policy[field])
    for field in ("reason_code", "evaluator"):
        identity(policy[field])
    unsigned = {key: value for key, value in policy.items() if key != "decision_digest"}
    require(audit_digest(unsigned) == policy["decision_digest"] == row["object_id"] == row["after_hash"]
            and metadata["request_id_digest"] == policy["request_id_digest"])
    surfaces, actors = _surface_contracts(tables, post_plan_ids)
    actor = identity(row["actor_user_id"])
    require(actor in actors and policy["actor_digest"] == _text_digest("principal.actor", actor.strip().casefold()))
    permissions = surfaces.get(policy["surface_digest"])
    require(permissions is not None)
    require(any(policy["required_permission_digest"] == audit_digest({"namespace": "permission.contract", "values": [permission]})
                and policy["granted_permission_digest"] == _text_digest("permission.granted", permission)
                for permission in cast(frozenset[str], permissions)))


def verify_audit_only_transition(before_tables: dict[str, Any], after_tables: dict[str, Any], *, tenant_id: str) -> dict[str, Any]:
    """Retain every business byte and independently verify only allowed audit appends."""
    tenant = identity(tenant_id)
    before, after = _capture_originals(before_tables, tenant), _capture_originals(after_tables, tenant)
    require(all(before[name] == after[name] for name in set(TABLES) - AUDIT_TABLES))
    old, new = _audit_chain(before, tenant), _audit_chain(after, tenant)
    require(len(new) >= len(old) and [raw for _row, raw in new[:len(old)]] == [raw for _row, raw in old])
    if len(old) == len(new):
        require(before["domain_audit_ledger_state"] == after["domain_audit_ledger_state"])
    for row, _raw in new[len(old):]:
        _policy_append(row, after)
    return {"business_tables": 76, "business_original_rows_equal": True, "audit_original_prefix_equal": True,
            "audit_chain_valid": True, "audit_actions_bound": True, "appended_audit_events": len(new) - len(old)}


def verify_raw_observations(packet: dict[str, Any], observations: dict[str, Any]) -> dict[str, Any]:
    """Check the closed HTTPS replay/read observations; financial arithmetic stays in qualify_raw_cycle."""
    require(type(observations) is dict and set(observations) == {"schema_version", "tenant_id", "source_order_id", "observations"}
            and observations["schema_version"] == "customer-partial-return-posted-observations-input-v1"
            and observations["tenant_id"] == packet["tenant_id"] and observations["source_order_id"] == packet["source_order_id"])
    rows = observations["observations"]
    require(type(rows) is list and len(rows) == 3 and len(packet["captures"]) == 9)
    chains = [_audit_chain(_capture_originals(capture, packet["tenant_id"]), packet["tenant_id"]) for capture in packet["captures"]]
    for old, new in zip(chains, chains[1:], strict=False):
        require(len(new) >= len(old) and [raw for _event, raw in new[:len(old)]] == [raw for _event, raw in old])
    count = 0
    for row, (kind, version) in zip(rows, (("RetainedReplay", 1), ("RetainedReplay", 6), ("FinalRead", 8)), strict=True):
        require(type(row) is dict and set(row) == {"schema_version", "kind", "tenant_id", "source_order_id", "history_version", "posted_plan_id", "plan_digest", "tables"}
                and row["schema_version"] == "customer-partial-return-browser-observation-v1" and row["kind"] == kind
                and row["tenant_id"] == packet["tenant_id"] and row["source_order_id"] == packet["source_order_id"]
                and type(row["history_version"]) is int and row["history_version"] == version)
        baseline = packet["captures"][version]
        history = sorted((decode_row(raw) for raw in baseline["customer_partial_return_history"]), key=lambda item: integer(item["sequence"], positive=True))
        require(len(history) == version and history[-1]["sequence"] == version and history[-1]["plan_id"] == row["posted_plan_id"])
        plan = row_index(tuple(decode_row(raw) for raw in baseline["customer_partial_return_plans"]))[identity(row["posted_plan_id"])]
        require(plan["phase"] == 2 and _hex(plan["plan_digest"]) == _hex(row["plan_digest"]) and plan["source_order_id"] == row["source_order_id"])
        result = verify_audit_only_transition(baseline, row["tables"], tenant_id=packet["tenant_id"])
        count += result["appended_audit_events"]
        old = _audit_chain(_capture_originals(baseline, packet["tenant_id"]), packet["tenant_id"])
        after = _capture_originals(row["tables"], packet["tenant_id"])
        observed_chain = _audit_chain(after, packet["tenant_id"])
        if version < 8:
            next_chain = chains[version + 1]
            require(len(next_chain) >= len(observed_chain)
                    and [raw for _event, raw in next_chain[:len(observed_chain)]] == [raw for _event, raw in observed_chain])
        for event, _raw in observed_chain[len(old):]:
            _policy_append(event, after, {row["posted_plan_id"]} if kind == "RetainedReplay" else set())
    return {"observations": 3, "retained_replay_observations": 2, "final_read_observations": 1, "observation_tables": 78,
            "observation_business_tables": 76, "observation_business_original_rows_equal": True,
            "observation_audit_prefix_original_bytes_equal": True, "observation_audit_chain_valid": True,
            "observation_audit_actions_bound": True, "observation_audit_chronology_valid": True, "observation_audit_appended_events": count}


def main() -> int:
    import argparse
    import hashlib
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Independently verify private posted partial-return SQL captures.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--restore-input", type=Path)
    parser.add_argument("--observations-input", type=Path)
    args = parser.parse_args()
    try:
        require(args.input.resolve() != args.output.resolve() and not args.output.exists())
        require(args.input.stat().st_size <= 32 * 1024 * 1024)
        original = args.input.read_bytes()
        packet = decode_row(original.decode("utf-8"), maximum_bytes=32 * 1024 * 1024)
        proof = qualify_raw_cycle(packet)
        observations = None
        if args.observations_input is not None:
            require(args.observations_input.stat().st_size <= 32 * 1024 * 1024)
            observation_original = args.observations_input.read_bytes()
            observations = decode_row(observation_original.decode("utf-8"), maximum_bytes=32 * 1024 * 1024)
            proof.update(verify_raw_observations(packet, observations))
            proof["observations_input_sha256"] = hashlib.sha256(observation_original).hexdigest()
        if args.restore_input is not None:
            require(args.restore_input.stat().st_size <= 32 * 1024 * 1024)
            restored_original = args.restore_input.read_bytes()
            proof.update(verify_raw_restore(packet, decode_row(restored_original.decode("utf-8"), maximum_bytes=32 * 1024 * 1024), observations=observations))
            proof["restore_input_sha256"] = hashlib.sha256(restored_original).hexdigest()
        proof.update(input_sha256=hashlib.sha256(original).hexdigest(), oracle_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(proof, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
    except (ValueError, OSError, KeyError, TypeError, OverflowError, RecursionError):
        print("Independent posted-cycle qualification refused.")
        return 2
    return 0


def verify_raw_restore(packet: dict[str, Any], restored: dict[str, Any], *, observations: dict[str, Any] | None = None) -> dict[str, Any]:
    """Require populated restored SQL originals to match final native custody."""
    require(type(restored) is dict and set(restored) == {"schema_version", "tenant_id", "source_order_id", "capture"})
    require(restored["schema_version"] == "customer-partial-return-posted-restore-input-v1"
            and restored["tenant_id"] == packet["tenant_id"] and restored["source_order_id"] == packet["source_order_id"])
    last = packet["captures"][-1]
    if observations is not None:
        verify_raw_observations(packet, observations)
        last = observations["observations"][-1]["tables"]
    current = restored["capture"]
    require(type(current) is dict and set(current) == set(last))
    for name, originals in last.items():
        require(type(current[name]) in {tuple, list} and sorted(current[name]) == sorted(originals))
    return {"populated_restore_original_rows_equal": True, "restored_tables": len(last),
            "restored_rows": sum(len(rows) for rows in last.values()), **({"restore_uses_final_observation": True} if observations is not None else {})}


if __name__ == "__main__":
    raise SystemExit(main())
