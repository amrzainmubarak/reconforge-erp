"""Internal read-only mapping of an already authorized native CR1 source.

This function creates no read/authorization boundary, claim, command or posting.
Its composing owner must supply its scoped connection and authorized original
envelope, and must acquire/revalidate the required locks before using a proposal.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from reconforge.domain.customer_partial_return_cost_evidence import OriginalRestitutedCostEvidence
from reconforge.domain.customer_partial_returns import (
    MAX_CONSUMPTIONS,
    OriginalConsumption,
    OriginalPartialReturnSource,
    OriginalPostingEvidence,
    PartialReturnScope,
    RestitutedOriginalConsumption,
)
from reconforge.domain.finance_posting import (
    FinancePostingError,
    canonical_json,
    digest_payload,
    text,
    validation_digest,
)
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.infrastructure.postgres_finance_posting import posting_entry, posting_snapshot, records
from reconforge.io.structured import StructuredDocumentError, StructuredDocumentPolicy, parse_json_document
from reconforge.platform.inventory_values import quantity_to_scaled

_ENVELOPE = {"stock", "invoice", "invoice_status", "invoice_version", "allocated_minor", "cogs", "revenue", "consumptions"}
_EXTENDED_OBSERVATION_POLICY = StructuredDocumentPolicy(max_file_bytes=8_388_608, max_nodes=200_000, max_depth=56,
    max_collection_items=4096, max_scalar_characters=6_291_456, max_yaml_aliases=1)
_OBSERVATION_POLICY = StructuredDocumentPolicy(max_file_bytes=2_097_152, max_nodes=50_000, max_depth=32,
    max_collection_items=1000, max_scalar_characters=131_072, max_yaml_aliases=1)


def _require(condition: bool) -> None:
    if not condition:
        raise FinancePostingError("customer_partial_return_source_invalid", "Original native partial-return source refused.")


def _one(connection: Any, query: str, args: tuple[Any, ...]) -> dict[str, Any]:
    rows = records(connection.execute(query, args))
    _require(len(rows) == 1)
    return rows[0]


def _observation(value: str, expected: type, *, extended: bool = False) -> Any:
    _require(type(value) is str)
    try:
        parsed = parse_json_document(value, reject_fractional_numbers=True, policy=_EXTENDED_OBSERVATION_POLICY if extended else _OBSERVATION_POLICY)
    except StructuredDocumentError as exc:
        raise FinancePostingError("customer_partial_return_source_invalid", "Original native partial-return source refused.") from exc
    _require(type(parsed) is expected)
    return parsed


def _same_scope(row: Mapping[str, Any], scope: PartialReturnScope) -> None:
    _require(all(row.get(field) == getattr(scope, field)
                 for field in ("tenant_id", "workspace_id", "organization_id", "legal_entity_id")))


def _effect(connection: Any, tenant: str, row: dict[str, Any], scope: PartialReturnScope,
            entry_id: str) -> OriginalPostingEvidence:
    _same_scope(row, scope)
    _require(row["entry_id"] == entry_id and row["source_kind"] == "Manual" and row["source_id"] == entry_id
             and row["purpose"] == "operational_posting" and row["reverses_effect_id"] is None
             and row["validation_contract_version"] == "finance-entry-review-v1")
    entry = posting_entry(connection, tenant, entry_id)
    _require(entry["status"] == "Validated" and entry["validation_digest"] == row["validation_digest"]
             and entry["validation_contract_version"] == row["validation_contract_version"]
             and len({entry["preparer_actor_id"], entry["validator_actor_id"], row["posted_actor_id"]}) == 3
             and all(type(person) is str and person for person in
                     (entry["preparer_actor_id"], entry["validator_actor_id"], row["posted_actor_id"])))
    native = posting_snapshot(connection, tenant, entry)
    _require(canonical_json(native) == canonical_json(row["snapshot_json"]))
    _require(all(type(row[key]) is type(native["entry"][key]) and row[key] == native["entry"][key]
                 for key in ("currency_code", "currency_precision", "currency_rounding_policy", "currency_registry_version", "currency_registry_digest")))
    return OriginalPostingEvidence(row["id"], scope, canonical_json(native), row["validation_digest"])


@dataclass(frozen=True)
class NativePartialReturnSourceEvidence:
    """Private native observations, separate from the Domain content digest.

    These are neither permission grants nor a durable claim. The posting owner
    must repeat membership checks under its actual transaction locks.
    JSON strings are canonical decoded content observations, not PostgreSQL
    original byte streams. Native NUMERIC invoice quantity is read separately
    as exact text; it is never converted through a binary float.
    """

    source: OriginalPartialReturnSource
    original_source_json: str
    collection_evidence_json: str

    def __post_init__(self) -> None:
        _require(type(self.source) is OriginalPartialReturnSource)
        original, collections = self.original_source(), self.collection_evidence()
        _require(type(original) is dict and set(original) == (_ENVELOPE | {"cost_admission"} if self.source.original_cost_admission is not None else _ENVELOPE)
                 and canonical_json(original) == self.original_source_json
                 and type(collections) is list and len(collections) <= 200
                 and canonical_json(collections) == self.collection_evidence_json)

    def original_source(self) -> dict[str, Any]:
        return cast(dict[str, Any], _observation(self.original_source_json, dict, extended=self.source.original_cost_admission is not None))

    def collection_evidence(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], _observation(self.collection_evidence_json, list))


def _collections(connection: Any, tenant: str, stock: dict[str, Any], invoice: dict[str, Any],
                 source: OriginalPartialReturnSource) -> list[dict[str, Any]]:
    allocations = records(connection.execute("""SELECT to_jsonb(a) allocation,to_jsonb(r) receipt
        FROM reconforge.ar_receipt_allocations a JOIN reconforge.ar_receipts r
        ON (r.tenant_id,r.id)=(a.tenant_id,a.receipt_id) WHERE a.tenant_id=%s AND a.invoice_id=%s
        ORDER BY a.receipt_id,a.id""", (tenant, invoice["id"])))
    _require(len(allocations) <= 200)
    observed: list[dict[str, Any]] = []
    cash_choices: set[str] = set()
    ar_line = source.original_revenue.snapshot()["lines"][0]
    for row in allocations:
        allocation, receipt = row["allocation"], row["receipt"]
        _same_scope(receipt, source.scope)
        _require(receipt["status"] == "Posted" and receipt["customer_id"] == stock["customer_id"]
                 and receipt["currency_code"] == source.currency_policy.currency_code
                 and type(allocation["amount_minor"]) is int and allocation["amount_minor"] > 0
                 and allocation["amount_minor"] == receipt["amount_minor"])
        _require(allocation["tenant_id"] == tenant and allocation["workspace_id"] == source.scope.workspace_id
                 and allocation["invoice_id"] == invoice["id"] and allocation["receipt_id"] == receipt["id"])
        membership = records(connection.execute("""SELECT to_jsonb(p) plan,to_jsonb(l) link,'Commercial' owner
            FROM reconforge.commercial_collection_plans p JOIN reconforge.commercial_collection_links l
            ON (l.tenant_id,l.plan_id)=(p.tenant_id,p.id)
            WHERE p.tenant_id=%s AND p.source_id=%s AND p.phase=2 AND l.receipt_id=%s
            UNION ALL SELECT to_jsonb(p),to_jsonb(l),'Stock' FROM reconforge.operational_finance_plans p
            JOIN reconforge.operational_finance_links l ON (l.tenant_id,l.plan_id)=(p.tenant_id,p.id)
            WHERE p.tenant_id=%s AND p.id=%s AND p.source_kind='ARReceipt' AND p.source_id=%s AND l.source_effect_id=%s""",
            (tenant, invoice["id"], receipt["id"], tenant, stock["collection_plan_id"], invoice["id"], receipt["id"])))
        _require(len(membership) == 1)
        owner = membership[0]
        _same_scope(owner["plan"], source.scope)
        _require(owner["plan"]["amount_minor"] == allocation["amount_minor"])
        if owner["owner"] == "Stock":
            _require(stock["status"] == "Paid" and stock["receipt_id"] == receipt["id"])
        effect = _one(connection, "SELECT to_jsonb(f) effect FROM reconforge.finance_posting_effects f WHERE tenant_id=%s AND id=%s",
                      (tenant, owner["link"]["posting_effect_id"]))["effect"]
        _require(owner["link"]["tenant_id"] == tenant and owner["link"]["plan_id"] == owner["plan"]["id"]
                 and owner["plan"]["entry_id"] == owner["plan"]["payload"]["entry_id"])
        evidence = _effect(connection, tenant, effect, source.scope, owner["plan"]["entry_id"])
        reviewed_digest = owner["plan"]["validation_digest"] if owner["owner"] == "Stock" else owner["plan"]["payload"]["validation_digest"]
        _require(owner["link"]["posted_actor_id"] == effect["posted_actor_id"]
                 and reviewed_digest == effect["validation_digest"]
                 and reviewed_digest == validation_digest(owner["plan"]["payload"]["snapshot"]))
        snapshot = evidence.snapshot()
        debit, credit = snapshot["lines"]
        _require(len(snapshot["lines"]) == 2 and snapshot["entry"]["external_reference"] == owner["plan"]["id"]
                 and debit["debit_minor"] == credit["credit_minor"] == allocation["amount_minor"]
                 and debit["credit_minor"] == credit["debit_minor"] == 0
                 and credit["account_id"] == ar_line["account_id"] and credit["dimensions"] == ar_line["dimensions"])
        source.currency_policy.require_compatible(FinancePolicyStore(connection, tenant_id=tenant).entry(receipt)[0])
        source.currency_policy.require_compatible(FinancePolicyStore(connection, tenant_id=tenant).entry(snapshot["entry"])[0])
        cash_choices.add(canonical_json({"account_id": debit["account_id"], "dimensions": debit["dimensions"]}))
        observed.append({"allocation": allocation, "receipt": receipt, "owner_kind": owner["owner"],
                         "owner_id": owner["plan"]["id"], "posting_effect": effect})
    _require(len(cash_choices) <= 1 and sum(row["allocation"]["amount_minor"] for row in observed) == source.collected_minor)
    return observed


def map_customer_partial_return_source(connection: Any, tenant_id: str,
                                       authorized_source: Mapping[str, Any]) -> NativePartialReturnSourceEvidence:
    """Rebind exact native memberships and preserve reviewed FIFO allocation order.

    No locks, transaction, permission grant or scope setter is introduced here.
    A digest proves content identity only; actual related rows are also read.
    """
    try:
        _require(type(tenant_id) is str and text(tenant_id, "tenant") == tenant_id)
        _require(isinstance(authorized_source, Mapping) and set(authorized_source) in (_ENVELOPE, _ENVELOPE | {"cost_admission"}))
        stock = authorized_source["stock"]
        _require(type(stock) is dict and type(stock["id"]) is str)
        selected = _one(connection, """SELECT current_setting('app.tenant_id',true) tenant_id,
            current_setting('app.workspace_id',true) workspace_id,current_setting('app.organization_id',true) organization_id,
            current_setting('app.legal_entity_id',true) legal_entity_id,current_setting('app.entity_id',true) entity_id""", ())
        scope = PartialReturnScope(tenant_id, stock["workspace_id"], stock["organization_id"], stock["legal_entity_id"],
                                   stock["item_id"], stock["location_id"], stock["uom_id"])
        _same_scope(selected, scope)
        _require(selected["entity_id"] == scope.legal_entity_id)
        extended = "cost_admission" in authorized_source
        getter = "SELECT reconforge.customer_partial_return_zero_stock_source(%s,%s) source" if extended else "SELECT reconforge.customer_return_source(%s,%s) source"
        fresh = _one(connection, getter, (tenant_id, stock["id"]))["source"]
        _require(type(fresh) is dict and canonical_json(fresh) == canonical_json(authorized_source))
        stock = fresh["stock"]
        invoice, cogs, revenue = fresh["invoice"], fresh["cogs"], fresh["revenue"]
        _require(all(type(row) is dict for row in (invoice, revenue)) and (type(cogs) is dict or (extended and cogs is None)))
        cost_admission = OriginalRestitutedCostEvidence(canonical_json(fresh["cost_admission"]), digest_payload(fresh["cost_admission"])) if extended else None
        _same_scope(stock, scope)
        _same_scope(invoice, scope)
        _require(stock["status"] in {"Invoiced", "Paid"} and fresh["invoice_status"] in {"Approved", "PartiallyPaid", "Paid"})
        _require(stock["invoice_id"] == invoice["id"] and stock["customer_id"] == invoice["customer_id"]
                 and stock["total_minor"] == invoice["total_minor"] and stock["currency_code"] == invoice["currency_code"])
        # Reuse existing scoped availability, including retained whole-credit
        # ownership and pending installment ambiguity. It performs no writes.
        connection.execute("SELECT reconforge.customer_return_source_available(%s,%s)", (tenant_id, stock["id"]))
        issue = stock["issue_plan"]
        _require(type(issue) is dict and issue["schema_version"] == ("stock-sales-issue-v2" if extended else "stock-sales-issue-v1")
                 and issue["source_digest"] == stock["source_digest"] and issue["entry_id"] == stock["cogs_entry_id"]
                 and digest_payload(stock["source"]) == stock["source_digest"])
        linked = _one(connection, """SELECT to_jsonb(p) plan,to_jsonb(l) link FROM reconforge.operational_finance_plans p
            JOIN reconforge.operational_finance_links l ON (l.tenant_id,l.plan_id)=(p.tenant_id,p.id)
            WHERE p.tenant_id=%s AND p.id=%s""", (tenant_id, stock["invoice_plan_id"]))
        plan, link = linked["plan"], linked["link"]
        _same_scope(plan, scope)
        _require(plan["source_kind"] == "ARInvoice" and plan["source_id"] == invoice["id"]
                 and plan["amount_minor"] == invoice["total_minor"] and plan["entry_id"] == revenue["entry_id"]
                 and link["posting_effect_id"] == revenue["id"] and link["source_effect_id"] == invoice["id"]
                 and link["posted_actor_id"] == revenue["posted_actor_id"]
                 and plan["validation_digest"] == revenue["validation_digest"] and stock["cogs_effect_id"] == (cogs["id"] if cogs is not None else None))
        original_cogs = _effect(connection, tenant_id, cogs, scope, stock["cogs_entry_id"]) if cogs is not None else None
        original_revenue = _effect(connection, tenant_id, revenue, scope, plan["entry_id"])
        policy, context = FinancePolicyStore(connection, tenant_id=tenant_id).entry(
            original_cogs.snapshot()["entry"] if original_cogs is not None else original_revenue.snapshot()["entry"])
        policy.require_compatible(FinancePolicyStore(connection, tenant_id=tenant_id).entry(original_revenue.snapshot()["entry"])[0])
        _require(canonical_json(issue["currency_policy"]) == canonical_json({
            "currency_code": policy.currency_code, "precision": policy.precision, "rounding_policy": policy.rounding_policy,
            "registry_version": policy.registry_version, "registry_digest": policy.registry_digest}))
        native = _one(connection, """SELECT to_jsonb(v) valuation,to_jsonb(vl) valuation_line,to_jsonb(m) movement,
            to_jsonb(ml) movement_line,to_jsonb(i) item,to_jsonb(e) entity,to_jsonb(claim) claim
            FROM reconforge.inventory_valuation_documents v
            JOIN reconforge.inventory_valuation_lines vl ON (vl.tenant_id,vl.valuation_document_id)=(v.tenant_id,v.id)
            JOIN reconforge.inventory_movements m ON (m.tenant_id,m.id)=(v.tenant_id,v.movement_id)
            JOIN reconforge.inventory_movement_lines ml ON (ml.tenant_id,ml.id)=(vl.tenant_id,vl.movement_line_id)
            JOIN reconforge.inventory_items i ON (i.tenant_id,i.id)=(vl.tenant_id,vl.item_id)
            JOIN reconforge.legal_entities e ON (e.tenant_id,e.id)=(v.tenant_id,v.legal_entity_id)
            JOIN reconforge.stock_sales_issue_claims claim ON claim.tenant_id=v.tenant_id AND claim.order_id=%s
            WHERE v.tenant_id=%s AND v.id=%s""", (stock["id"], tenant_id, stock["valuation_id"]))
        valuation, detail, movement, movement_line = (native[key] for key in ("valuation", "valuation_line", "movement", "movement_line"))
        for row in (valuation, movement):
            _same_scope(row, scope)
        _require(valuation["status"] == "Approved" and valuation["finance_entry_id"] == (original_cogs.entry_id if original_cogs is not None else None)
                 and valuation["total_value_minor"] == issue["total_cost_minor"] and valuation["movement_id"] == stock["movement_id"]
                 and detail["value_minor"] == issue["total_cost_minor"]
                 and movement["status"] == "Posted" and movement["movement_type"] == "Delivery"
                 and movement["source_reference"] == stock["id"] and detail["flow_direction"] == "Outbound")
        for row in (detail, movement_line):
            _require(row["tenant_id"] == tenant_id and row["item_id"] == scope.item_id and row["uom_id"] == scope.uom_id
                     and row["quantity_scaled"] == stock["quantity_scaled"] and row["quantity_precision"] == stock["quantity_precision"]
                     and "inventory_lot_id" in row and row["inventory_lot_id"] is None)
        _require(movement_line["from_location_id"] == scope.location_id and movement_line["to_location_id"] is None
                 and native["item"]["uom_id"] == scope.uom_id and native["item"]["tracking_mode"] == "None"
                 and native["item"]["item_type"] in ("Stock", "Consumable") and native["item"]["workspace_id"] == scope.workspace_id
                 and native["item"]["organization_id"] in (None, scope.organization_id)
                 and native["entity"]["organization_id"] == scope.organization_id
                 and native["entity"]["currency_code"] == policy.currency_code
                 and native["claim"]["state"] == "Consumed" and native["claim"]["entry_id"] == (original_cogs.entry_id if original_cogs is not None else None)
                 and all(native["claim"][key] == getattr(scope, key)
                         for key in ("tenant_id", "workspace_id", "legal_entity_id", "item_id"))
                 and native["claim"]["order_id"] == stock["id"] and native["claim"]["plan_digest"] == digest_payload(issue)
                 and canonical_json(native["claim"]["payload"]) == canonical_json(issue))
        line = _one(connection, """SELECT quantity::text quantity_numeric_text,quantity_text,unit_price_minor,tax_minor,line_total_minor
            FROM reconforge.ar_invoice_lines WHERE tenant_id=%s AND invoice_id=%s""", (tenant_id, invoice["id"]))
        _require(quantity_to_scaled(line["quantity_numeric_text"], stock["quantity_precision"]) == stock["quantity_scaled"]
                 and quantity_to_scaled(line["quantity_text"], stock["quantity_precision"]) == stock["quantity_scaled"]
                 and line["unit_price_minor"] == stock["source"]["net_unit_price_minor"]
                 and line["tax_minor"] == invoice["tax_minor"] and line["line_total_minor"] == invoice["total_minor"])
        allocations, consumptions = issue["allocations"], fresh["consumptions"]
        _require(type(allocations) is list and type(consumptions) is list
                 and 1 <= len(allocations) == len(consumptions) <= MAX_CONSUMPTIONS)
        by_layer = {row["cost_layer_id"]: row for row in consumptions}
        _require(len(by_layer) == len(consumptions) and len({row["cost_layer_id"] for row in allocations}) == len(allocations))
        original_consumptions = []
        for position, allocation in enumerate(allocations, 1):
            consumption = by_layer[allocation["cost_layer_id"]]
            _require(consumption["tenant_id"] == tenant_id and consumption["workspace_id"] == scope.workspace_id
                     and consumption["valuation_line_id"] == detail["id"]
                     and all(type(allocation[key]) is type(consumption[key]) is int and allocation[key] == consumption[key]
                             for key in ("quantity_scaled", "value_minor")))
            origin = _one(connection, """SELECT to_jsonb(l) layer,to_jsonb(v) original_line,to_jsonb(d) original_document
                FROM reconforge.inventory_cost_layers l JOIN reconforge.inventory_valuation_lines v
                ON (v.tenant_id,v.id)=(l.tenant_id,l.source_valuation_line_id)
                JOIN reconforge.inventory_valuation_documents d ON (d.tenant_id,d.id)=(v.tenant_id,v.valuation_document_id)
                WHERE l.tenant_id=%s AND l.id=%s""", (tenant_id, consumption["cost_layer_id"]))
            layer, original_line, original_document = (origin[key] for key in ("layer", "original_line", "original_document"))
            _require(all(layer[key] == getattr(scope, key) for key in ("tenant_id", "workspace_id", "legal_entity_id", "item_id", "uom_id"))
                     and layer["inventory_lot_id"] is None and layer["quantity_precision"] == stock["quantity_precision"])
            _same_scope(original_document, scope)
            _require(original_document["status"] == "Approved" and original_line["flow_direction"] == "Inbound"
                     and original_line["item_id"] == scope.item_id and original_line["uom_id"] == scope.uom_id
                     and original_line["inventory_lot_id"] is None and original_line["quantity_precision"] == stock["quantity_precision"]
                     and original_line["quantity_scaled"] == layer["original_quantity_scaled"])
            # The original inbound valuation carries retained policy. A cost
            # layer has no policy columns; never invent them or consult master.
            policy.require_compatible(FinancePolicyStore(connection, tenant_id=tenant_id).entry(original_document)[0])
            consumption_type = RestitutedOriginalConsumption if extended else OriginalConsumption
            original_consumptions.append(consumption_type(position, consumption["id"], consumption["valuation_line_id"],
                consumption["cost_layer_id"], scope, stock["quantity_precision"], consumption["quantity_scaled"], consumption["value_minor"], policy.currency_code))
        typed = OriginalPartialReturnSource(scope, stock["id"], invoice["id"], stock["valuation_id"], plan["id"],
            stock["quantity_precision"], stock["quantity_scaled"], invoice["total_minor"], line["unit_price_minor"], fresh["allocated_minor"],
            policy, context, original_cogs, original_revenue, tuple(original_consumptions), native["entity"]["currency_code"],
            native["item"]["uom_id"], tax_minor=invoice["tax_minor"], inventory_lot_id=detail["inventory_lot_id"],
            serial_tracked=native["item"]["tracking_mode"] == "Serial", original_cost_admission=cost_admission)
        collections = _collections(connection, tenant_id, stock, invoice, typed)
        return NativePartialReturnSourceEvidence(typed, canonical_json(fresh), canonical_json(collections))
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise FinancePostingError("customer_partial_return_source_invalid", "Original native partial-return source refused.") from exc
