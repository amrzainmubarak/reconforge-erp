"""Independent finite CR3 zero-cost restitution/resale/IT1 financial proof.

This NEW reader preserves the positive-original raw91 reader byte-for-byte.
It admits only the declared six-stage synthetic lineage, derives original net,
each tax component, historical FX, both Return cuts and all real journals from
actual SQL rows. It proves neither current authorization nor the later failed
parent reversal/cancellation, which occur after the last captured checkpoint.
No production financial module or database driver is imported.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import re
import stat
import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

BASE_SHA256 = "72ac6163d886d6527010a3eadd2827d39461e4242a3c5581718c3eb6bc2c7ddb"
BASE_PATH = Path(__file__).absolute().with_name("customer_partial_return_monetary_posted_oracle.py")


def _bootstrap(path: Path) -> bytes:
    """Read only the fixed pinned dependency, bounded before importing it."""
    for candidate in (*reversed(path.parents), path):
        info = candidate.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Independent monetary restitution dependency refused.")
        if not (stat.S_ISREG(info.st_mode) if candidate == path else stat.S_ISDIR(info.st_mode)):
            raise ValueError("Independent monetary restitution dependency refused.")
    if info.st_size > 256 * 1024:
        raise ValueError("Independent monetary restitution dependency refused.")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        original = stream.read(256 * 1024 + 1)
    after = path.lstat()
    identities = [(row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns) for row in (info, opened, after)]
    if len(original) != info.st_size or len(set(identities)) != 1:
        raise ValueError("Independent monetary restitution dependency refused.")
    return original


_base_bytes = _bootstrap(BASE_PATH)
if hashlib.sha256(_base_bytes).hexdigest() != BASE_SHA256:
    raise ValueError("Independent monetary restitution dependency refused.")
_spec = importlib.util.spec_from_file_location("_monetary_positive_raw91_frozen", BASE_PATH)
if _spec is None or _spec.loader is None:
    raise ValueError("Independent monetary restitution dependency refused.")
base = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = base
_spec.loader.exec_module(base)
if _bootstrap(BASE_PATH) != _base_bytes:
    raise ValueError("Independent monetary restitution dependency refused.")
Capture, OriginalFinancial = base.Capture, base.OriginalFinancial
require, _minor, _one, _scope = base.require, base._minor, base._one, base._scope
_identity, _policy, _full_policy = base._identity, base._policy, base._full_policy
_nearest, _day, _rate, _effect, _digest = base._nearest, base._day, base._rate, base._effect, base._digest
TABLES = base.TABLES
SCHEMA = "customer-partial-return-monetary-restituted-cycle-input-v1"
CHECKPOINTS = ("Original", "OldZeroReturn", "ResaleInvoiced", "ResaleReturned", "TransferPosted", "TransferInversePosted")
OUTBOX_FIELDS = frozenset(["tenant_id", "event_id", "event_type", "aggregate_type", "aggregate_id", "workspace_id", "organization_id", "legal_entity_id", "payload", "created_at"])


@dataclass(frozen=True)
class RestitutedPacket:
    tenant_id: str
    original_source_order_id: str
    resale_source_order_id: str
    captures: tuple[Any, ...]
    sha256: str


def decode_packet(original: bytes) -> RestitutedPacket:
    require(type(original) is bytes and 0 < len(original) <= base.MAX_PACKET_BYTES)
    value = base._decode(original)
    require(type(value) is dict and set(value) == {"schema_version", "tenant_id", "original_source_order_id", "resale_source_order_id", "captures"}
            and value["schema_version"] == SCHEMA)
    tenant, old, new = (_identity(value[key]) for key in ("tenant_id", "original_source_order_id", "resale_source_order_id"))
    require(old != new and type(value["captures"]) is list and len(value["captures"]) == 6)
    captures = []
    for index, (label, capture) in enumerate(zip(CHECKPOINTS, value["captures"], strict=True)):
        require(type(capture) is dict and set(capture) == {"checkpoint", "tables"} and capture["checkpoint"] == label)
        captures.append(base.decode_capture({"capture": index, "tables": capture["tables"]}, index=index, tenant_id=tenant))
    return RestitutedPacket(tenant, old, new, tuple(captures), hashlib.sha256(original).hexdigest())


def verify_zero_original_rows(capture: Any, *, source_order_id: str) -> Any:
    """New explicit zero-cost original; positive original admission stays frozen."""
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
    require(sum(q for q, _ in fifo) == quantity and all(value == 0 for _, value in fifo)
            and _minor(stock["issue_plan"]["total_cost_minor"]) == 0
            and stock["issue_plan"]["cost_admission_policy"] == "partial-return-restituted-v1"
            and source["original_cost_admission_digest"] == _digest(stock["issue_plan"])
            and stock["cogs_entry_id"] is stock["cogs_effect_id"] is document["finance_entry_id"] is None)
    evidence = body["evidence"]
    require(type(evidence) is dict and set(evidence) == {"stock_order_id", "stock_source", "stock_source_digest", "issue_plan", "movement_id", "valuation_id",
        "cogs_entry_id", "cogs_effect_id", "cogs_snapshot", "fx_source", "recognition_plan_id", "recognition_snapshot", "invoice_id", "invoice_original", "invoice_line", "consumptions", "roles", "dimensions"})
    require(evidence["stock_order_id"] == stock["id"] and evidence["stock_source"] == declared and evidence["stock_source_digest"] == stock["source_digest"]
            and all(evidence[key] == stock[key] for key in ("issue_plan", "movement_id", "valuation_id", "cogs_entry_id", "cogs_effect_id", "invoice_id"))
            and evidence["cogs_snapshot"] is None and evidence["recognition_snapshot"] == revenue["snapshot_json"]
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


def _native_projection(capture: Any, movement_id: str, supplied: Any) -> tuple[bool, bool]:
    """Bind the closed immutable native snapshot, not mutable delivery columns."""
    require(type(supplied) is dict and set(supplied) == {"head", "lines", "audit", "outbox"})
    head = _one(capture, "inventory_movements", id=movement_id)
    lines = sorted((row for row in capture.rows("inventory_movement_lines") if row["movement_id"] == movement_id),
                   key=lambda row: (_minor(row["line_number"], positive=True), row["id"]))
    audits = sorted((row for row in capture.rows("domain_audit_events") if row["object_type"] == "inventory_movement" and row["object_id"] == movement_id),
                    key=lambda row: (_minor(row["sequence"], positive=True), row["id"]))
    outbox = sorted(({key: row[key] for key in OUTBOX_FIELDS} for row in capture.rows("outbox_events")
                     if row["aggregate_type"] == "inventory_movement" and row["aggregate_id"] == movement_id), key=lambda row: row["event_id"])
    _same(supplied, {"head": head, "lines": lines, "audit": audits, "outbox": outbox})
    return bool(audits), bool(outbox)


def _native(capture: Any, movement_id: str, supplied: Any) -> None:
    require(all(_native_projection(capture, movement_id, supplied)))


def _receipt_native(capture: Any, plan: dict[str, Any], supplied: Any) -> None:
    """IRP owns three plan events; its directly created movement has no generic event."""
    require(not any(_native_projection(capture, plan["movement_id"], supplied)))
    body = plan["plan_json"]
    review = _one(capture, "inventory_receipt_reviews", plan_id=plan["id"])
    reviewed = review["review_json"]
    link = _one(capture, "inventory_receipt_links", plan_id=plan["id"])
    scope = {key: plan[key] for key in ("tenant_id", "workspace_id", "organization_id", "legal_entity_id")}
    for row in (plan, review, link, supplied["head"]):
        _scope(row, scope)
    require(body["contract_version"] == "inventory-receipt-plan-v1" and reviewed["contract_version"] == "inventory-receipt-review-v1"
            and _minor(plan["plan_version"], positive=True) == _minor(body["plan_version"], positive=True)
            == _minor(review["plan_version"], positive=True) == _minor(reviewed["plan_version"], positive=True) == 1
            and body["operation"] == plan["operation"] == "Receipt" and body["original"] is None
            and body["plan_id"] == plan["id"] and reviewed["plan_id"] == link["plan_id"] == plan["id"]
            and reviewed["review_id"] == review["id"] == link["review_id"]
            and body["plan_digest"] == plan["plan_digest"] == review["plan_digest"] == reviewed["plan_digest"] == link["plan_digest"]
            and plan["plan_digest"] == _digest({key: value for key, value in body.items()
                                               if key not in {"plan_digest", "preparation_audit_event_id", "preparation_outbox_event_id"}})
            and reviewed["review_digest"] == review["review_digest"] == link["review_digest"]
            and review["review_digest"] == _digest({key: value for key, value in reviewed.items()
                                                   if key not in {"review_digest", "audit_event_id", "outbox_event_id"}})
            and body["finance_validation_digest"] == plan["finance_validation_digest"] == review["finance_validation_digest"] == reviewed["finance_validation_digest"]
            and plan["finance_validation_digest"] == _digest(body["finance_snapshot"]))
    entry = _one(capture, "finance_entries", id=plan["finance_entry_id"])
    _same(body["scope"], {**{key: scope[key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
                          "organization_code": entry["organization_code"], "entity_code": entry["entity_code"]})
    _same(body["preparer"], {"user_id": plan["preparer_actor_id"], "username": plan["preparer_username"]})
    _same(reviewed["reviewer"], {"user_id": review["reviewer_actor_id"], "username": review["reviewer_username"]})
    effect = _one(capture, "finance_posting_effects", id=link["posting_effect_id"])
    _scope(effect, scope)
    _same(body["finance_snapshot"], effect["snapshot_json"])
    require(effect["posted_actor_id"] == link["posted_actor_id"] and effect["validation_digest"] == plan["finance_validation_digest"])
    for key, value in body["artifacts"].items():
        if key.endswith("_id"):
            _same(link[key], value)
    require(link["movement_id"] == plan["movement_id"] and len({plan["preparer_actor_id"], review["reviewer_actor_id"], link["posted_actor_id"]}) == 3)
    common = {"plan_digest": plan["plan_digest"], "finance_validation_digest": plan["finance_validation_digest"]}
    for owner, audit_key, outbox_key, actor, action, metadata in (
        (plan, "preparation_audit_event_id", "preparation_outbox_event_id", plan["preparer_actor_id"], "inventory_receipt_prepared", common),
        (review, "audit_event_id", "outbox_event_id", review["reviewer_actor_id"], "inventory_receipt_reviewed", {**common, "review_digest": review["review_digest"]}),
        (link, "audit_event_id", "outbox_event_id", link["posted_actor_id"], "inventory_receipt_committed", {**common, "review_digest": review["review_digest"], "effect_id": body["artifacts"]["posting_effect_id"]}),
    ):
        audit = _one(capture, "domain_audit_events", id=owner[audit_key])
        outbox = _one(capture, "outbox_events", event_id=owner[outbox_key])
        _scope(outbox, scope)
        require(audit["tenant_id"] == scope["tenant_id"] and audit["actor_user_id"] == actor
                and audit["object_type"] == "inventory_receipt_posting" and audit["object_id"] == plan["id"]
                and audit["action"] == action and outbox["aggregate_type"] == "inventory_receipt_posting"
                and outbox["aggregate_id"] == plan["id"] and outbox["event_type"] == action)
        _same(audit["metadata_json"], metadata)
        _same(outbox["payload"], {**metadata, "audit_event_id": audit["id"]})
    require(body["preparation_audit_event_id"] == plan["preparation_audit_event_id"]
            and body["preparation_outbox_event_id"] == plan["preparation_outbox_event_id"]
            and reviewed["audit_event_id"] == review["audit_event_id"] and reviewed["outbox_event_id"] == review["outbox_event_id"])


def _same(supplied: Any, actual: Any) -> None:
    """Nested bools and exact numeric lexemes cannot borrow integer equality."""
    require(type(supplied) is type(actual))
    if type(actual) is dict:
        require(set(supplied) == set(actual))
        for key in actual:
            _same(supplied[key], actual[key])
    elif type(actual) is list:
        require(len(supplied) == len(actual))
        for left, right in zip(supplied, actual, strict=True):
            _same(left, right)
    else:
        require(supplied == actual)


def _stock_physical(capture: Any, original: Any) -> None:
    stock = _one(capture, "stock_sales_orders", id=original.source["source_order_id"])
    movement = _one(capture, "inventory_movements", id=stock["movement_id"])
    _scope(movement, original.scope)
    line = _one(capture, "inventory_movement_lines", movement_id=movement["id"])
    require(movement["status"] == "Posted" and movement["movement_type"] == "Delivery"
            and movement["source_type"] == "Generated" and movement["source_reference"] == stock["id"]
            and line["item_id"] == stock["item_id"] and line["uom_id"] == stock["uom_id"]
            and type(line["quantity_precision"]) is int and line["quantity_precision"] == 1
            and _minor(line["quantity_scaled"], positive=True) == original.source["quantity_scaled"]
            and line["from_location_id"] == stock["location_id"] and line["to_location_id"] is None
            and line["inventory_lot_id"] is None)
    actors = []
    for operation in ("prepare-issue", "review-issue", "deliver"):
        event = _one(capture, "stock_sales_events", order_id=stock["id"], operation=operation)
        actors.append(_identity(event["actor_id"]))
        audit = _one(capture, "domain_audit_events", id=event["audit_event_id"])
        require(audit["actor_user_id"] == event["actor_id"] and audit["object_type"] == "stock_sales"
                and audit["object_id"] == stock["id"] and audit["action"] == "stock_sales." + operation
                and audit["metadata_json"] == {"source_digest": stock["source_digest"], "version": event["version"], "status": event["status"]})
    require(len(set(actors)) == 3 and actors[0] == stock["issue_plan"]["preparer_actor_id"]
            and actors[1] == stock["issue_reviewer_id"])
    document = _one(capture, "inventory_valuation_documents", id=stock["valuation_id"])
    details = [row for row in capture.rows("inventory_valuation_lines") if row["valuation_document_id"] == document["id"]]
    require(len(details) == 1 and _minor(document["total_value_minor"]) == sum(v for _, v in original.fifo)
            and _minor(details[0]["quantity_scaled"], positive=True) == original.source["quantity_scaled"]
            and _minor(details[0]["value_minor"]) == document["total_value_minor"])
    reservations = [row for row in capture.rows("stock_sales_reservations") if row["order_id"] == stock["id"]]
    claims = [row for row in capture.rows("stock_sales_issue_claims") if row["order_id"] == stock["id"]]
    require(len(reservations) == len(claims) == 1 and reservations[0]["state"] == claims[0]["state"] == "Consumed")
    _scope(reservations[0], original.scope)
    _scope(claims[0], {key: value for key, value in original.scope.items() if key != "organization_id"})
    require(reservations[0]["location_id"] == stock["location_id"] and reservations[0]["item_id"] == claims[0]["item_id"] == stock["item_id"]
            and _minor(reservations[0]["quantity_scaled"], positive=True) == stock["quantity_scaled"]
            and claims[0]["entry_id"] == stock["cogs_entry_id"] and claims[0]["plan_digest"] == _digest(stock["issue_plan"]))
    _same(claims[0]["payload"], stock["issue_plan"])


def _origin_memberships(capture: Any, original: Any) -> None:
    """Use the frozen per-owner contract without concealing global memberships."""
    plans = {row["id"] for row in capture.rows("customer_partial_return_monetary_plans") if row["origin_id"] == original.origin_id}
    filtered = []
    for table, values in capture.raw_tables:
        if table == "stock_sales_monetary_origins":
            values = tuple(raw for raw in values if base._decode(raw)["id"] == original.origin_id)
        elif table == "customer_partial_return_monetary_plans":
            values = tuple(raw for raw in values if base._decode(raw)["id"] in plans)
        elif table.startswith("customer_partial_return_monetary_") and table != "customer_partial_return_monetary_history":
            values = tuple(raw for raw in values if base._decode(raw)["plan_id"] in plans)
        filtered.append((table, values))
    base._native_memberships(Capture(capture.index, tuple(filtered), capture.sha256), original)


def _correction(capture: Any, supplied: Any) -> None:
    require(type(supplied) is dict and set(supplied) == {"restoration", "source", "plan", "entry", "effect", "lines", "dimensions", "physical", "history_sequence", "allocation_policy"})
    restored = supplied["restoration"]
    actual = _one(capture, "customer_partial_return_monetary_restorations", plan_id=restored["plan_id"], position=restored["position"])
    plan = _one(capture, "customer_partial_return_monetary_plans", id=actual["plan_id"])
    origin = _one(capture, "stock_sales_monetary_origins", id=plan["origin_id"])
    stock = _one(capture, "stock_sales_orders", id=origin["stock_order_id"])
    history = _one(capture, "customer_partial_return_monetary_history", origin_id=origin["id"], partial_plan_id=plan["id"])
    expected_source = {"id": origin["id"], "source_digest": origin["source_digest"], "stock_order_id": stock["id"],
        **{key: stock[key] for key in ("workspace_id", "organization_id", "legal_entity_id", "item_id", "uom_id", "quantity_precision", "location_id")},
        "original_cogs_effect_id": stock["cogs_effect_id"], "original_cost_minor": stock["issue_plan"]["total_cost_minor"]}
    expected_plan = {**{key: plan[key] for key in ("id", "operation", "phase", "plan_digest")}, "source_id": origin["id"], "functional_cost_minor": 0}
    _same(restored, actual)
    _same(supplied["source"], expected_source)
    _same(supplied["plan"], expected_plan)
    require(type(supplied["history_sequence"]) is int and supplied["history_sequence"] == history["sequence"] == 1
            and supplied["allocation_policy"] == "remaining-dual-currency-v1"
            and supplied["entry"] is supplied["effect"] is actual["correction_effect_id"] is None
            and supplied["lines"] == supplied["dimensions"] == []
            and _minor(plan["payload"]["monetary_event"]["monetary"]["functional_cost_minor"]) == 0)
    _native(capture, actual["physical_movement_id"], supplied["physical"])


def _zero_admission(capture: Any, supplied: Any, stock: dict[str, Any], consumed: dict[str, Any]) -> None:
    require(type(supplied) is dict and set(supplied) == {"consumption_id", "stock_order_id", "cost_admission_policy", "issue_plan", "valuation_document", "valuation_line", "posting_effect", "physical"})
    document = _one(capture, "inventory_valuation_documents", id=stock["valuation_id"])
    detail = _one(capture, "inventory_valuation_lines", id=consumed["valuation_line_id"])
    require(supplied["consumption_id"] == consumed["id"] and supplied["stock_order_id"] == stock["id"]
            and supplied["cost_admission_policy"] == stock["issue_plan"]["cost_admission_policy"] == "partial-return-restituted-v1"
            and supplied["issue_plan"] == stock["issue_plan"] and supplied["valuation_document"] == document
            and supplied["valuation_line"] == detail and supplied["posting_effect"] is None
            and _minor(consumed["value_minor"]) == _minor(document["total_value_minor"]) == 0
            and stock["cogs_entry_id"] is stock["cogs_effect_id"] is document["finance_entry_id"] is None)
    _native(capture, stock["movement_id"], supplied["physical"])


def _pool(capture: Any, supplied: Any, old: Any, *, corrections: int, zero_stock: dict[str, Any] | None) -> None:
    require(type(supplied) is dict and set(supplied) == {"schema_version", "monetary_policy", "remaining_quantity_scaled", "remaining_value_minor", "sources"}
            and supplied["schema_version"] == "inventory-transfer-cost-v4"
            and supplied["monetary_policy"] == _full_policy(old.source["functional_policy"])
            and _minor(supplied["remaining_quantity_scaled"], positive=True) == 1 and _minor(supplied["remaining_value_minor"]) == 0
            and type(supplied["sources"]) is list and len(supplied["sources"]) == 1)
    item = supplied["sources"][0]
    keys = {"layer", "valuation_document", "valuation_line", "receipt_plan", "receipt_link", "receipt_review", "finance_entry", "finance_lines", "posting_effect", "receipt_native", "valuation_input", "consumptions", "exposed_amounts_minor", "partial_return_corrections", "monetary_return_corrections"}
    require(type(item) is dict and set(item) == keys | ({"restituted_consumption_admissions"} if zero_stock is not None else set()))
    layer = _one(capture, "inventory_cost_layers", id=old.source["consumptions"][0]["cost_layer_id"])
    require(item["layer"] == layer and (_minor(layer["original_quantity_scaled"], positive=True), _minor(layer["original_value_minor"], positive=True)) == (10, 1)
            and (_minor(layer["remaining_quantity_scaled"]), _minor(layer["remaining_value_minor"])) == (1, 0))
    plan = _one(capture, "inventory_receipt_plans", valuation_line_id=layer["source_valuation_line_id"])
    link = _one(capture, "inventory_receipt_links", plan_id=plan["id"])
    review = _one(capture, "inventory_receipt_reviews", id=link["review_id"])
    document = _one(capture, "inventory_valuation_documents", id=plan["valuation_document_id"])
    detail = _one(capture, "inventory_valuation_lines", id=plan["valuation_line_id"])
    effect = _one(capture, "finance_posting_effects", id=link["posting_effect_id"])
    entry = _one(capture, "finance_entries", id=effect["entry_id"])
    lines = sorted((row for row in capture.rows("finance_entry_lines") if row["entry_id"] == entry["id"]), key=lambda row: row["line_number"])
    consumed = sorted((row for row in capture.rows("inventory_layer_consumptions") if row["cost_layer_id"] == layer["id"]), key=lambda row: row["id"])
    require(item["valuation_document"] == document and item["valuation_line"] == detail and item["receipt_plan"] == plan["plan_json"]
            and item["receipt_link"] == link and item["receipt_review"] == review["review_json"]
            and item["finance_entry"] == entry and item["finance_lines"] == lines and item["posting_effect"] == effect
            and item["valuation_input"] == _one(capture, "inventory_valuation_input_costs", id=plan["input_cost_id"])
            and item["consumptions"] == consumed and item["partial_return_corrections"] == [])
    _receipt_native(capture, plan, item["receipt_native"])
    expected_exposed = [layer["original_value_minor"], layer["remaining_value_minor"], document["total_value_minor"], detail["value_minor"], plan["total_value_minor"], entry["total_debit_minor"], entry["total_credit_minor"]]
    expected_exposed += [row["debit_minor"] for row in lines] + [row["credit_minor"] for row in lines]
    require(type(item["exposed_amounts_minor"]) is list and all(type(value) is int for value in item["exposed_amounts_minor"])
            and item["exposed_amounts_minor"] == expected_exposed)
    parts = item["monetary_return_corrections"]
    actual = capture.rows("customer_partial_return_monetary_restorations")
    require(type(parts) is list and len(parts) == corrections == len(actual)
            and {part["restoration"]["plan_id"] for part in parts} == {row["plan_id"] for row in actual})
    for part in parts:
        _correction(capture, part)
    if zero_stock is not None:
        zero_consumed = _one(capture, "inventory_layer_consumptions", valuation_line_id=_one(capture, "inventory_valuation_lines", valuation_document_id=zero_stock["valuation_id"])["id"])
        admissions = item["restituted_consumption_admissions"]
        require(type(admissions) is list and len(admissions) == 1)
        _zero_admission(capture, admissions[0], zero_stock, zero_consumed)


def _transfers(capture: Any, original: Any, *, expected_count: int, pool: Any) -> set[str]:
    sources = capture.rows("inventory_transfer_sources")
    require(len(sources) == expected_count)
    movement_ids = set()
    for source in sources:
        _scope(source, original.scope)
        body = source["payload"]
        require(_minor(source["phase"]) == 2 and _minor(source["row_version"], positive=True) == 3
                and body["id"] == source["id"] and body["schema_version"] == "inventory-transfer-v1"
                and source["source_digest"] == _digest(body) and body["cost_snapshot"] == pool
                and source["review_cost_json"] == pool and source["review_cost_digest"] == _digest(pool)
                and _minor(source["quantity_scaled"], positive=True) == 1
                and type(source["quantity_precision"]) is int and source["quantity_precision"] == 1
                and source["item_id"] == _one(capture, "stock_sales_orders", id=original.source["source_order_id"])["item_id"])
        _same(body["scope"], {key: value for key, value in original.scope.items() if key != "tenant_id"})
        for key in ("item_id", "uom_id", "quantity_precision", "quantity_scaled", "from_location_id", "to_location_id", "period_id", "posting_date", "number", "native_movement_id", "creator_actor_id"):
            _same(body[key], source[key])
        people = [source[key] for key in ("creator_actor_id", "reviewer_actor_id", "poster_actor_id")]
        require(all(type(person) is str and bool(person) for person in people) and len(set(people)) == 3)
        events = sorted((row for row in capture.rows("inventory_transfer_events") if row["transfer_id"] == source["id"]), key=lambda row: _minor(row["version"], positive=True))
        commands = sorted((row for row in capture.rows("inventory_transfer_commands") if row["transfer_id"] == source["id"]), key=lambda row: _minor(row["version"], positive=True))
        require(len(events) == len(commands) == 3)
        for index, (event, command) in enumerate(zip(events, commands, strict=True), 1):
            operation = ("inverse-create" if source["original_transfer_id"] is not None else "create") if index == 1 else "review" if index == 2 else "post"
            require(_minor(event["version"], positive=True) == _minor(command["version"], positive=True) == index
                    and event["operation"] == command["operation"] == operation
                    and event["actor_id"] == command["actor_id"] == people[index - 1]
                    and event["request_json"] == command["request_json"]
                    and event["request_digest"] == command["request_digest"] == _digest(command["request_json"]))
            audit = _one(capture, "domain_audit_events", id=event["audit_event_id"])
            outbox = _one(capture, "outbox_events", event_id=event["outbox_event_id"])
            metadata = {"source_digest": source["source_digest"], "version": index, "operation": operation, "reason": event["reason"]}
            require(audit["actor_user_id"] == people[index - 1] and audit["object_type"] == "inventory_transfer"
                    and audit["object_id"] == source["id"] and audit["action"] == "inventory_transfer." + operation
                    and audit["metadata_json"] == metadata and outbox["aggregate_type"] == "inventory_transfer"
                    and outbox["aggregate_id"] == source["id"] and outbox["event_type"] == audit["action"]
                    and outbox["payload"] == {**metadata, "audit_event_id": audit["id"]})
            _scope(outbox, original.scope)
            response = command["response_json"]
            require(response["source"]["id"] == source["id"] and response["source"]["source_digest"] == source["source_digest"]
                    and response["source"]["row_version"] == index and response["source"]["phase"] == index - 1)
            _same(response["native_response"], response["source"]["native_response"])
            _same(response["native_response"], source["posted_native_json"] if index == 3 else source["native_creation_json"])
            _same(response["source"]["review_cost_snapshot"], None if index == 1 else pool)
        movement = _one(capture, "inventory_movements", id=source["native_movement_id"])
        _scope(movement, original.scope)
        line = _one(capture, "inventory_movement_lines", movement_id=movement["id"])
        require(movement["status"] == "Posted" and movement["movement_type"] == "Transfer"
                and movement["source_type"] == "Generated" and movement["source_reference"] == source["id"]
                and movement["posted_by"] == people[2] and movement["movement_date"] == source["posting_date"]
                and line["item_id"] == source["item_id"] and line["uom_id"] == source["uom_id"]
                and _minor(line["quantity_scaled"], positive=True) == 1 and type(line["quantity_precision"]) is int and line["quantity_precision"] == 1
                and line["from_location_id"] == source["from_location_id"] and line["to_location_id"] == source["to_location_id"])
        _native(capture, movement["id"], source["posted_native_json"])
        created = source["native_creation_json"]
        require(type(created) is dict and set(created) == {"head", "lines", "audit", "outbox"}
                and created["head"]["status"] == "Draft" and _minor(created["head"]["row_version"], positive=True) == 1)
        mutable = {"status", "posted_by", "posted_at", "post_reason", "updated_at", "row_version"}
        _same({key: value for key, value in created["head"].items() if key not in mutable},
              {key: value for key, value in movement.items() if key not in mutable})
        _same(created["lines"], source["posted_native_json"]["lines"])
        require(bool(created["audit"]) and bool(created["outbox"]))
        for event in created["audit"]:
            _same(event, _one(capture, "domain_audit_events", id=event["id"]))
        for event in created["outbox"]:
            _same(event, {key: _one(capture, "outbox_events", event_id=event["event_id"])[key] for key in OUTBOX_FIELDS})
        claim = _one(capture, "inventory_transfer_claims", transfer_id=source["id"])
        release = _one(capture, "inventory_transfer_releases", transfer_id=source["id"])
        guard = _one(capture, "inventory_quantity_source_guards", id=claim["id"])
        _one(capture, "inventory_quantity_source_releases", guard_id=claim["id"], release_id=release["id"])
        require(claim["state"] == "Posted" and claim["location_id"] == source["from_location_id"]
                and _minor(claim["quantity_scaled"], positive=True) == 1 and release["claim_id"] == claim["id"]
                and release["purpose"] == "Post" and release["target_movement_id"] == movement["id"]
                and release["actor_id"] == people[2] and guard["owner_namespace"] == "IT1" and guard["owner_claim_id"] == claim["id"])
        if source["original_transfer_id"] is not None:
            parent = _one(capture, "inventory_transfer_sources", id=source["original_transfer_id"])
            require(parent["original_transfer_id"] is None and source["from_location_id"] == parent["to_location_id"]
                    and source["to_location_id"] == parent["from_location_id"]
                    and body["original"] == {"id": parent["id"], "source_digest": parent["source_digest"], "version": parent["row_version"],
                                              "native_response": parent["posted_native_json"], "review_cost_snapshot": parent["review_cost_json"]})
        else:
            require(body["original"] is None)
        movement_ids.add(movement["id"])
    require(len(movement_ids) == expected_count)
    return movement_ids


def _physical_totals(capture: Any, old: Any, expected: tuple[int, int]) -> None:
    stock = _one(capture, "stock_sales_orders", id=old.source["source_order_id"])
    locations = {row["id"]: row for row in capture.rows("inventory_locations")}
    totals: dict[str, int] = {}
    for movement in capture.rows("inventory_movements"):
        if movement["status"] != "Posted":
            continue
        _scope(movement, old.scope)
        for line in capture.rows("inventory_movement_lines"):
            if line["movement_id"] != movement["id"]:
                continue
            require(line["item_id"] == stock["item_id"] and line["uom_id"] == stock["uom_id"]
                    and type(line["quantity_precision"]) is int and line["quantity_precision"] == 1 and line["inventory_lot_id"] is None)
            quantity = _minor(line["quantity_scaled"], positive=True)
            for field, sign in (("from_location_id", -1), ("to_location_id", 1)):
                identifier = line[field]
                if identifier is not None:
                    require(identifier in locations)
                    totals[identifier] = totals.get(identifier, 0) + sign * quantity
    main = stock["location_id"]
    others = {identifier: value for identifier, value in totals.items() if identifier != main}
    require(totals.get(main, 0) == expected[0] and sum(others.values()) == expected[1] and all(value >= 0 for value in totals.values()))
    if expected[1]:
        require(len(others) == 1)


def qualify_raw_cycle(packet: RestitutedPacket) -> dict[str, Any]:
    old = base.verify_original_rows(packet.captures[0], source_order_id=packet.original_source_order_id)
    require(old.source["quantity_scaled"] == 10 and old.source["quantity_precision"] == 1
            and old.components == ((10, 3), (1, 0)) and old.fifo == ((10, 1),)
            and old.source["transaction_policy"]["currency_code"] == "EUR" and old.source["functional_policy"]["currency_code"] == "USD")
    new = verify_zero_original_rows(packet.captures[2], source_order_id=packet.resale_source_order_id)
    require(new.scope == old.scope and new.origin_id != old.origin_id and new.source["quantity_scaled"] == new.source["quantity_precision"] == 1
            and new.components == ((100, 100), (14, 14)) and new.fifo == ((1, 0),)
            and new.source["transaction_policy"] == new.source["functional_policy"] == old.source["functional_policy"])
    previous_chain: tuple[str, ...] = ()
    totals = []
    pool = None
    originals: dict[str, Any] = {}
    for index, capture in enumerate(packet.captures):
        require({row["id"] for row in capture.rows("stock_sales_orders")} == ({packet.original_source_order_id} if index < 2 else {packet.original_source_order_id, packet.resale_source_order_id}))
        require(len(capture.rows("stock_sales_monetary_origins")) == (1 if index < 2 else 2)
                and len(capture.rows("inventory_layer_consumptions")) == (1 if index < 2 else 2)
                and len(capture.rows("customer_partial_return_monetary_restorations")) == (0 if index == 0 else 1 if index < 3 else 2))
        chain = base._audit_chain(capture, packet.tenant_id)
        require(chain[:len(previous_chain)] == previous_chain)
        previous_chain = chain
        if index:
            base._immutable_transition(packet.captures[index - 1], capture)
        origin_ids = {row["id"] for row in capture.rows("stock_sales_monetary_origins")}
        plan_ids = {row["id"] for row in capture.rows("customer_partial_return_monetary_plans")}
        require(all(row["origin_id"] in origin_ids for row in capture.rows("customer_partial_return_monetary_plans")))
        for table in ("customer_partial_return_monetary_entries", "customer_partial_return_monetary_events", "customer_partial_return_monetary_restorations", "customer_partial_return_monetary_commands"):
            require(all(row["plan_id"] in plan_ids for row in capture.rows(table)))
        physical = {row["movement_id"] for row in capture.rows("inventory_receipt_plans")}
        allowed: set[str] = base._receipt_effects(capture, old)
        for source, first, expected_events in ((old, 0, 0 if index == 0 else 1), *(([(new, 2, 0 if index == 2 else 1)]) if index >= 2 else [])):
            check = base.verify_original_rows(capture, source_order_id=source.source["source_order_id"]) if first == 0 else verify_zero_original_rows(capture, source_order_id=source.source["source_order_id"])
            require(check.fingerprint == source.fingerprint)
            origin = _one(capture, "stock_sales_monetary_origins", id=source.origin_id)
            immutable = {key: value for key, value in origin.items() if key != "ar_balance"}
            if source.origin_id in originals:
                require(originals[source.origin_id] == immutable)
            else:
                originals[source.origin_id] = immutable
            stock = _one(capture, "stock_sales_orders", id=source.source["source_order_id"])
            _stock_physical(capture, source)
            physical.add(stock["movement_id"])
            events = base.verify_history_rows(capture, source)
            require(len(events) == expected_events and all(event["kind"] == "Return" and event["quantity_scaled"] == 1 for event in events))
            if events:
                event = events[0]
                require(event["monetary"]["transaction_credit_minor"] == (1 if first == 0 else 114)
                        and event["monetary"]["functional_credit_minor"] == (0 if first == 0 else 114)
                        and event["monetary"]["functional_cost_minor"] == 0)
                restoration = _one(capture, "customer_partial_return_monetary_restorations", origin_id=source.origin_id)
                require(_minor(restoration["consumption_count_at_restore"], positive=True) == (1 if first == 0 else 2))
            allowed.update(base.verify_posted_journal_rows(capture, source, events))
            physical.update(base.verify_physical_rows(capture, source, events))
            closing, active = base.verify_valuation_rows(capture, source, events)
            require(not closing and active is None)
            base._projection(capture, source, events, None)
            _origin_memberships(capture, source)
            if stock["cogs_effect_id"] is not None:
                allowed.add(stock["cogs_effect_id"])
            allowed.add(_one(capture, "operational_fx_links", plan_id=stock["invoice_plan_id"])["posting_effect_id"])
        require(len(capture.rows("customer_partial_return_monetary_history")) == (0 if index == 0 else 1 if index < 3 else 2)
                and all(not capture.rows(table) for table in ("ar_receipts", "ar_receipt_allocations", "customer_partial_return_history", "customer_partial_return_restorations")))
        totals.append(base._ledger(capture, old, allowed))
        require(totals[-1] == ((3, 6, 5) if index < 2 else (4, 9, 119) if index == 2 else (5, 12, 233)))
        if index == 2:
            resale = _one(capture, "stock_sales_orders", id=packet.resale_source_order_id)
            _pool(packet.captures[1], resale["issue_plan"]["restitution_cost_snapshot"], old, corrections=1, zero_stock=None)
        if index >= 4:
            transfers = capture.rows("inventory_transfer_sources")
            forward = next((row for row in transfers if row["original_transfer_id"] is None), None)
            if forward is None:
                raise base.MonetaryRawRefusal("Independent monetary restituted raw input refused.")
            if pool is None:
                pool = forward["payload"]["cost_snapshot"]
            _pool(capture, pool, old, corrections=2, zero_stock=_one(capture, "stock_sales_orders", id=packet.resale_source_order_id))
            physical.update(_transfers(capture, old, expected_count=index - 3, pool=pool))
        else:
            require(not capture.rows("inventory_transfer_sources"))
        require({row["id"] for row in capture.rows("inventory_movements")} == physical
                and all(row["status"] == "Posted" for row in capture.rows("inventory_movements"))
                and all(row["movement_id"] in physical for row in capture.rows("inventory_movement_lines")))
        _physical_totals(capture, old, (0, 0) if index in {0, 2} else (0, 1) if index == 4 else (1, 0))
    final = packet.captures[-1]
    balances: dict[str, int] = {}
    for row in final.rows("finance_entry_lines"):
        balances[row["account_id"]] = balances.get(row["account_id"], 0) + _minor(row["debit_minor"]) - _minor(row["credit_minor"])
    clearing = _one(final, "inventory_receipt_plans")["receipt_clearing_account_id"]
    require({account: value for account, value in balances.items() if value} == {clearing: -1, old.roles["cogs_account_id"]: 1, old.roles["receivable_account_id"]: 3, old.roles["revenue_account_id"]: -3})
    return {"schema_version": "independent-monetary-restituted-cycle-proof-v1", "status": "passed", "captures": 6, "tables": 91,
            "sources": 2, "governed_returns": 2, "transfers": 2, "final_posting_effects": 5, "final_posted_lines": 12,
            "final_debits_minor": "233", "final_credits_minor": "233", "explicit_zero_original_cost_admission": True,
            "zero_financial_entries_omitted": True, "original_rows_immutable": True, "active_prefix_witnesses": True,
            "posted_journals_bound": True, "physical_restorations_bound": True, "transfer_inverse_bound": True,
            "audit_chain_valid": True, "audit_original_prefix_equal": True, "current_authorization_proven": False,
            "later_dependency_refusal_proven": False, "populated_restore_proven": False, "input_sha256": packet.sha256}


def qualify_files(input_path: Path) -> dict[str, Any]:
    original = base.read_original(input_path)
    own_path = Path(__file__).absolute()
    own_bytes = base.read_original(own_path)
    dependency = base.read_original(BASE_PATH)
    require(hashlib.sha256(dependency).hexdigest() == BASE_SHA256)
    proof = qualify_raw_cycle(decode_packet(original))
    proof.update(oracle_source_sha256=hashlib.sha256(own_bytes).hexdigest(), positive_raw91_dependency_sha256=BASE_SHA256)
    for path, value in ((input_path, original), (own_path, own_bytes), (BASE_PATH, dependency)):
        base.require_original_unchanged(path, value)
    return proof


def main() -> int:
    parser = argparse.ArgumentParser(description="Independently verify the finite monetary zero-cost resale/return/transfer lineage.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        proof = qualify_files(args.input)
        base._write_new(args.output, proof)
    except (base.MonetaryRawRefusal, OSError, ValueError, TypeError, KeyError, IndexError, OverflowError):
        parser.exit(2, "Independent monetary restituted raw input refused.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

