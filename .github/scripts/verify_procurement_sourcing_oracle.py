"""Independent raw-evidence sourcing oracle: stdlib only, no ReconForge imports."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

MAX_MINOR = 9_000_000_000_000_000_000


class OracleError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise OracleError(message)


def integer(value: Any, *, positive: bool = False) -> int:
    if isinstance(value, str):
        require(re.fullmatch(r"0|[1-9][0-9]{0,18}", value) is not None, "Canonical integer evidence required")
        value = int(value)
    require(type(value) is int and (1 if positive else 0) <= value <= MAX_MINOR, "Bounded exact integer evidence required")
    return value


def quantity(value: Any) -> Fraction:
    require(isinstance(value, str) and re.fullmatch(r"[0-9]+(?:\.[0-9]{1,6})?", value) is not None,
        "Quantity evidence requires exact decimal text")
    result = Fraction(value)
    require(result > 0 and result <= MAX_MINOR, "Positive bounded source quantity required")
    return result


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def seal(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def indexed(rows: list[dict[str, Any]], key: str = "id") -> dict[str, dict[str, Any]]:
    result = {row[key]: row for row in rows}
    require(len(result) == len(rows), "Duplicate raw evidence identity")
    return result


def exact_total(lines: list[dict[str, Any]], *, price_key: str = "unit_price_minor", quantity_key: str = "quantity") -> int:
    total = Fraction()
    for line in lines:
        value = quantity(line[quantity_key]) * integer(line[price_key], positive=True)
        require(value.denominator == 1, "A financial product cannot silently round fractional minor units")
        total += value
    require(total.denominator == 1, "Exact source financial total required")
    return integer(total.numerator, positive=True)


def verify(packet: dict[str, Any]) -> dict[str, Any]:
    require(packet.get("schema_version") == "sourcing-oracle-v1", "Unsupported oracle evidence schema")
    source = packet["source"]
    payload = source["payload"]
    require(seal(payload) == source["source_digest"], "Original demand source seal differs")
    require(source["phase"] == 3, "Oracle accepts an actually awarded original source")
    scope = payload["scope"]
    require(all(source[key] == scope[key] for key in ("workspace_id", "organization_id", "legal_entity_id")), "Source hierarchy differs")
    currency = payload["request"]["order"]["currency_code"]
    require(integer(payload["currency_precision"]) <= 8, "Explicit retained currency precision required")
    tenant = source["tenant_id"]
    native = packet["native"]
    def bound(row: dict[str, Any]) -> None:
        require(row["tenant_id"] == tenant, "Raw source tenant differs")
        require(all(row[key] == scope[key] for key in scope if key in row), "Raw source hierarchy differs")
    for row in [packet["commitment"], packet["budget"], native["order"], *packet["quotes"], *packet["source_events"],
                *packet["source_commands"], *packet["source_audits"], *packet["source_outbox"], *packet["budget_events"],
                *packet["commitment_commands"], *(row for rows in native.values() if isinstance(rows, list) for row in rows)]:
        bound(row)
    ceiling = exact_total(payload["request"]["order"]["lines"])
    require(ceiling == integer(source["ceiling_minor"], positive=True) == integer(payload["ceiling_minor"], positive=True), "Original ceiling differs from independent demand arithmetic")
    quotes = indexed(packet["quotes"])
    require(1 <= len(quotes) <= 32 and len({q["supplier_code"] for q in quotes.values()}) == len(quotes), "Unique bounded original suppliers required")
    for quote in quotes.values():
        q = quote["payload"]
        require(seal(q) == quote["quote_digest"] and q["source_digest"] == source["source_digest"] and q["requisition_id"] == quote["requisition_id"] == source["id"]
                and q["registrar_actor_id"] == quote["registrar_actor_id"] and q["supplier_id"] == quote["supplier_id"], "Supplier offer source seal differs")
        original = payload["request"]["order"]
        order = q["order"]
        require(order["number"] == "BPC1-" + original["number"] and order["supplier_code"] == quote["supplier_code"], "Offer native order identity differs")
        require({k: v for k, v in order.items() if k not in {"number", "supplier_code", "lines"}} ==
                {k: v for k, v in original.items() if k not in {"number", "supplier_code", "lines"}}, "Quotation changes original operational terms")
        require(len(order["lines"]) == len(original["lines"]) == len(q["quotation"]["unit_prices_minor"]), "Offer completeness differs")
        for old, new, price in zip(original["lines"], order["lines"], q["quotation"]["unit_prices_minor"], strict=True):
            require({k: v for k, v in old.items() if k != "unit_price_minor"} == {k: v for k, v in new.items() if k != "unit_price_minor"}
                    and integer(new["unit_price_minor"], positive=True) == integer(price, positive=True), "Offer changes original item, quantity or warehouse")
        require(exact_total(order["lines"]) == integer(quote["total_minor"], positive=True) == integer(q["total_minor"], positive=True), "Supplier offer independent arithmetic differs")
    winner = min(quotes.values(), key=lambda q: (integer(q["total_minor"], positive=True), q["supplier_code"]))
    awarded = integer(winner["total_minor"], positive=True)
    require(winner["id"] == source["selected_quote_id"] and awarded <= ceiling, "Selected original offer differs from deterministic admissible minimum")
    history = sorted(packet["source_events"], key=lambda event: integer(event["version"], positive=True))
    require([integer(event["version"], positive=True) for event in history] == list(range(1, integer(source["row_version"], positive=True) + 1))
            and [event["operation"] for event in history] == ["create", "open-rfq", *(["quote"] * len(quotes)), "review-selection", "award"], "Original consecutive source history differs")
    commands = indexed(packet["source_commands"], "command_id")
    audits, outbox = indexed(packet["source_audits"]), indexed(packet["source_outbox"], "event_id")
    require(len(commands) == len(audits) == len(outbox) == len(history), "Original event/command/evidence membership differs")
    for event in history:
        command, audit, published = commands[event["command_id"]], audits[event["audit_event_id"]], outbox[event["outbox_event_id"]]
        require(event["requisition_id"] == source["id"] and seal(event["request_json"]) == event["request_digest"]
                and event["request_json"]["operation"] == event["operation"] and event["request_json"]["actor_id"] == event["actor_id"], "Original command request seal differs")
        require(all(command[key] == event[key] for key in ("requisition_id", "version", "actor_id", "request_json", "request_digest")), "Original retained acknowledgment owner differs")
        metadata = {"source_digest": source["source_digest"], "command_id": event["command_id"], "request_digest": event["request_digest"],
                    "version": event["version"], "operation": event["operation"], "reason": event["reason"]}
        require(audit["object_type"] == "procurement_sourcing" and audit["object_id"] == source["id"] and audit["actor_user_id"] == event["actor_id"]
                and audit["action"] == "procurement_sourcing_" + event["operation"] and audit["metadata_json"] == metadata
                and published["aggregate_type"] == "procurement_sourcing" and published["aggregate_id"] == source["id"]
                and published["event_type"] == audit["action"] and published["payload"] == {**metadata, "audit_event_id": audit["id"]}, "Original audit/outbox evidence differs")
        ack = command["response_json"]
        require(ack["id"] == source["id"] and ack["row_version"] == event["version"] and ack["source_digest"] == source["source_digest"]
                and all(ack[key] == scope[key] for key in scope) and ack["evidence"] == {"audit_event_id": audit["id"], "outbox_event_id": published["event_id"], "request_digest": event["request_digest"]}, "Historical acknowledgment source identity differs")
        if event["operation"] == "quote":
            retained = [q for q in quotes.values() if q["created_version"] == event["version"]]
            require(len(retained) == 1 and retained[0]["registrar_actor_id"] == event["actor_id"]
                    and retained[0]["payload"]["quotation"] == event["request_json"]["request"]["quotation"], "Original quote event differs")
    events = {e["operation"]: e for e in history if e["operation"] != "quote"}
    required = {"create", "open-rfq", "review-selection", "award"}
    require(set(events) == required, "Actual sourcing approval sequence differs")
    creator, reviewer, poster = (events[key]["actor_id"] for key in ("create", "review-selection", "award"))
    require(len({creator, reviewer, poster}) == 3 and events["open-rfq"]["actor_id"] != creator, "Original three-person sourcing ownership differs")
    require(all(q["registrar_actor_id"] != reviewer for q in quotes.values()) and winner["registrar_actor_id"] != poster
            and poster != events["open-rfq"]["actor_id"], "Offer registrar or approver cannot publish own original award")
    purchase = native["order"]
    # Retained multiline PO additionally carries the existing first-line compatibility fields.
    compatibility = {"item_code", "quantity", "unit_price_minor", "location_code", "policy_code"}
    native_order = {key: value for key, value in purchase["request_json"].items() if key not in compatibility}
    require(all(purchase["request_json"][key] == purchase["request_json"]["lines"][0][key] for key in compatibility if key in purchase["request_json"]), "Native first-line compatibility source differs")
    require(purchase["id"] == source["order_id"] and native_order == winner["payload"]["order"]
            and integer(purchase["total_minor"], positive=True) == awarded and purchase["creator_actor_id"] == poster, "Native purchase differs from original reviewed award")
    commitment = packet["commitment"]
    require(seal(commitment["payload"]) == commitment["plan_digest"] and commitment["order_id"] == purchase["id"]
            and commitment["payload"]["order_request"] == native_order and commitment["budget_id"] == source["budget_id"], "Native appropriation owner differs")
    budget = packet["budget"]
    require(budget["id"] == commitment["budget_id"] and budget["currency_code"] == currency
            and budget["currency_precision"] == payload["currency_precision"] and budget["period_id"] == purchase["request_json"]["period_id"]
            and commitment["payload"]["scope"] == scope and commitment["payload"]["amount_minor"] == awarded, "Original appropriation policy differs")
    lines = indexed(native["lines"])
    require(all(row["order_id"] == purchase["id"] for rows in (native["lines"], native["receipts"], native["invoices"], native["invoice_lines"])
                for row in rows if "order_id" in row), "Native child original purchase differs")
    ordered = sorted(lines.values(), key=lambda line: line["sequence"])
    require(len(ordered) == len(purchase["request_json"]["lines"]), "Native purchase lines differ")
    for line, original in zip(ordered, purchase["request_json"]["lines"], strict=True):
        require(line["item_code"] == original["item_code"] and quantity(line["quantity_text"]) == quantity(original["quantity"])
                and line["unit_price_minor"] == original["unit_price_minor"] and line["location_code"] == original["location_code"]
                and quantity(line["quantity_text"]) * integer(line["unit_price_minor"], positive=True) == integer(line["total_minor"], positive=True), "Native exact line differs")
    receipt_plans = indexed(native["receipt_plans"])
    receipt_links = indexed(native["receipt_links"], "plan_id")
    layers = indexed(native["layers"])
    effects = indexed(native["effects"])
    accounts = indexed(native["accounts"])
    expected_effects: dict[str, dict[str, int]] = {}
    def expect_effect(identifier: str, debit: str, credit: str, amount: int) -> None:
        require(identifier not in expected_effects and debit != credit, "Original native effect identity or mapping duplicates")
        expected_effects[identifier] = {debit: amount, credit: -amount}
    received = {key: Fraction() for key in lines}
    receipt_total = 0
    for receipt in native["receipts"]:
        line = lines[receipt["order_line_id"]]
        value = quantity(receipt["quantity_text"]) * integer(line["unit_price_minor"], positive=True)
        require(value.denominator == 1 and value == integer(receipt["total_minor"], positive=True), "Receipt financial arithmetic differs")
        require(receipt["stage"] == 2, "Oracle requires actually posted receipts")
        plan, link = receipt_plans[receipt["receipt_plan_id"]], receipt_links[receipt["receipt_plan_id"]]
        require(plan["operation"] == "Receipt" and integer(plan["total_value_minor"], positive=True) == value
                and quantity(receipt["quantity_text"]) * 10 ** integer(plan["quantity_precision"]) == integer(plan["quantity_scaled"], positive=True)
                and plan["item_id"] == line["item_id"] and plan["location_id"] == line["location_id"], "Native original receipt source differs")
        require(plan["currency_code"] == currency and plan["currency_precision"] == payload["currency_precision"]
                and link["posting_effect_id"] == plan["posting_effect_id"] and link["cost_layer_id"] == plan["cost_layer_id"], "Native original receipt link differs")
        layer = layers[link["cost_layer_id"]]
        require(layer["original_value_minor"] == value and layer["original_quantity_scaled"] == plan["quantity_scaled"], "Original FIFO layer differs")
        consumed_q = sum(integer(c["quantity_scaled"], positive=True) for c in native["layer_consumptions"] if c["cost_layer_id"] == layer["id"])
        consumed_v = sum(integer(c["value_minor"], positive=True) for c in native["layer_consumptions"] if c["cost_layer_id"] == layer["id"])
        require(layer["original_quantity_scaled"] == integer(layer["remaining_quantity_scaled"]) + consumed_q
                and layer["original_value_minor"] == integer(layer["remaining_value_minor"]) + consumed_v, "Original FIFO quantity/value conservation differs")
        expect_effect(link["posting_effect_id"], plan["inventory_account_id"], plan["receipt_clearing_account_id"], int(value))
        received[line["id"]] += quantity(receipt["quantity_text"])
        receipt_total += int(value)
    require(all(received[key] <= quantity(line["quantity_text"]) for key, line in lines.items()), "Receiving exceeds original demand")
    require(set(receipt_plans) == set(receipt_links) == {receipt["receipt_plan_id"] for receipt in native["receipts"]}
            and set(layers) == {link["cost_layer_id"] for link in receipt_links.values()}, "Original receipt/layer membership differs")
    invoices = indexed(native["invoices"])
    native_invoices = indexed(native["native_invoices"])
    accrued_q = {key: Fraction() for key in lines}
    consumed_total = 0
    paid_total = 0
    ap = next(a["id"] for a in accounts.values() if a["account_code"] == purchase["request_json"]["ap_account_code"])
    cash = next(a["id"] for a in accounts.values() if a["account_code"] == purchase["request_json"]["cash_account_code"])
    clearing = {plan["receipt_clearing_account_id"] for plan in receipt_plans.values()}
    require(len(clearing) == 1, "One native AP clearing mapping required")
    for invoice in invoices.values():
        parts = [part for part in native["invoice_lines"] if part["invoice_id"] == invoice["id"]]
        require(bool(parts) and len({p["order_line_id"] for p in parts}) == len(parts), "Original invoice completeness differs")
        total = 0
        for part in parts:
            value = quantity(part["quantity_text"]) * integer(lines[part["order_line_id"]]["unit_price_minor"], positive=True)
            require(value.denominator == 1 and value == integer(part["total_minor"], positive=True), "Invoice independent line arithmetic differs")
            total += int(value)
            accrued_q[part["order_line_id"]] += quantity(part["quantity_text"])
        header = native_invoices[invoice["native_invoice_id"]]
        require(invoice["stage"] == 4 and total == integer(invoice["total_minor"], positive=True) == integer(header["total_minor"], positive=True)
                and header["currency_code"] == currency and integer(header["tax_minor"]) == 0, "Original native posted AP or unsupported FX/tax differs")
        expect_effect(invoice["accrual_effect_id"], next(iter(clearing)), ap, total)
        payments = [p for p in native["payments"] if p["supplier_invoice_id"] == header["id"]]
        paid = sum(integer(p["amount_minor"], positive=True) for p in payments)
        require(paid <= total and header["status"] == ("Paid" if paid == total else "Approved"), "Native AP settlement differs")
        for payment in payments:
            expect_effect(payment["posting_effect_id"], ap, cash, integer(payment["amount_minor"], positive=True))
        consumed_total += total
        paid_total += paid
    require(all(accrued_q[key] <= received[key] for key in lines), "Invoicing exceeds actual receiving")
    require(set(native_invoices) == {invoice["native_invoice_id"] for invoice in invoices.values()}
            and all(part["invoice_id"] in invoices for part in native["invoice_lines"])
            and all(payment["supplier_invoice_id"] in native_invoices for payment in native["payments"]), "Original native AP child membership differs")
    source_events = [e for e in packet["budget_events"] if e["commitment_id"] == commitment["commitment_id"]]
    reserves = [e for e in source_events if e["operation"] == "Reserve"]
    require(len(reserves) == 1 and reserves[0]["id"] == commitment["reserve_event_id"] and reserves[0]["amount_minor"] == awarded, "Original native Reserve differs")
    consumed = sum(integer(e["amount_minor"], positive=True) for e in source_events if e["operation"] == "Consume")
    released = sum(integer(e["amount_minor"], positive=True) for e in source_events if e["operation"] == "Release")
    require(consumed == consumed_total and consumed + released <= awarded, "AP and appropriation conservation differs")
    owners = indexed(packet["commitment_commands"], "budget_event_id")
    require(set(owners) == {event["id"] for event in source_events}, "Native budget/AP owner membership differs")
    for event in source_events:
        owner = owners[event["id"]]
        require(owner["operation"] == {"Reserve": "create", "Consume": "consume", "Release": "release"}[event["operation"]]
                and owner["order_id"] == purchase["id"] and seal(owner["request_json"]) == owner["request_digest"], "Native appropriation command owner differs")
        if event["operation"] == "Consume":
            require(integer(event["amount_minor"], positive=True) == invoices[owner["invoice_id"]]["total_minor"], "Native AP consumption source differs")
    remaining = awarded
    for event in sorted(source_events, key=lambda event: integer(event["budget_version"], positive=True)):
        if event["operation"] != "Reserve":
            remaining -= integer(event["amount_minor"], positive=True)
        require(remaining >= 0 and remaining == integer(event["remaining_minor"]), "Original commitment remaining history differs")
    all_reserved, all_consumed = 0, 0
    require(len({event["budget_version"] for event in packet["budget_events"]}) == len(packet["budget_events"]), "Budget event version duplicates")
    for event in sorted(packet["budget_events"], key=lambda event: integer(event["budget_version"], positive=True)):
        require(event["budget_id"] == budget["id"] and event["operation"] in {"Reserve", "Consume", "Release"}, "Budget source events differ")
        amount = integer(event["amount_minor"], positive=True)
        all_reserved += amount if event["operation"] == "Reserve" else -amount
        all_consumed += amount if event["operation"] == "Consume" else 0
        require(all_reserved >= 0 and all_reserved + all_consumed <= integer(budget["limit_minor"], positive=True), "Intermediate budget envelope conservation differs")
    require((all_reserved, all_consumed) == (integer(budget["reserved_minor"]), integer(budget["consumed_minor"]))
            and all_reserved + all_consumed <= integer(budget["limit_minor"], positive=True), "Independent budget envelope conservation differs")
    require(set(effects) == set(expected_effects), "Native GL effect membership differs")
    for identifier, expected in expected_effects.items():
        effect = effects[identifier]
        snapshot = effect["snapshot_json"]
        require(seal(snapshot) == effect["validation_digest"] and snapshot["entry"]["currency_code"] == currency
                and effect["currency_code"] == currency and effect["currency_precision"] == payload["currency_precision"]
                and all(snapshot["entry"][key] == scope[key] for key in scope), "Native posting seal/currency/hierarchy differs")
        actual: dict[str, int] = {}
        debit, credit = 0, 0
        for line in snapshot["lines"]:
            dr, cr = integer(line["debit_minor"]), integer(line["credit_minor"])
            require((dr > 0) != (cr > 0), "Each native GL line needs exactly one side")
            actual[line["account_id"]] = actual.get(line["account_id"], 0) + dr - cr
            debit += dr
            credit += cr
        require(debit == credit and actual == expected, "Independent original operational/financial GL effect differs")
    return {"schema_version": "sourcing-oracle-result-v1", "verified": True, "source_id": source["id"], "source_digest": source["source_digest"],
        "input_sha256": seal(packet), "ceiling_minor": str(ceiling), "awarded_minor": str(winner["total_minor"]),
        "received_minor": str(receipt_total), "consumed_minor": str(consumed_total), "paid_minor": str(paid_total), "released_minor": str(released),
        "source_reserved_minor": str(awarded - consumed - released), "effect_count": len(effects),
        "budget_available_minor": str(integer(budget["limit_minor"]) - all_reserved - all_consumed)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    try:
        packet = json.loads(args.input.read_text(encoding="utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(OracleError("Nonfinite JSON refused")))
        print(canonical(verify(packet)))
        return 0
    except (OracleError, KeyError, IndexError, TypeError, StopIteration, ValueError) as exc:
        print(canonical({"schema_version": "sourcing-oracle-result-v1", "verified": False, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
