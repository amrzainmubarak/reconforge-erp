"""Explicit factual evidence for original governed restituted-cost stock issues.

This type attests supplied canonical content only. The native Stock owner must
prove its source/physical/valuation ownership; a digest is not database admission.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from reconforge.domain.finance_posting import FinancePostingError, canonical_json, digest_payload, validation_digest
from reconforge.io.structured import StructuredDocumentPolicy, parse_json_document

STOCK_RESTITUTED_COST_POLICY = "partial-return-restituted-v1"
ORIGINAL_COST_EVIDENCE_VERSION = "stock-sales-restituted-cost-v1"
COST_EVIDENCE_JSON_POLICY = StructuredDocumentPolicy(max_file_bytes=6_291_456, max_nodes=131_072,
    max_depth=48, max_collection_items=4096, max_scalar_characters=262_144, max_yaml_aliases=1)


def _require(condition: bool) -> None:
    if not condition:
        raise FinancePostingError("partial_return_cost_evidence_invalid", "Original restituted-cost evidence refused.")


@dataclass(frozen=True, slots=True)
class OriginalRestitutedCostEvidence:
    evidence_json: str
    evidence_digest: str

    def __post_init__(self) -> None:
        self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        try:
            _require(type(self.evidence_json) is str and type(self.evidence_digest) is str)
            parsed = parse_json_document(self.evidence_json, policy=COST_EVIDENCE_JSON_POLICY, reject_fractional_numbers=True)
            _require(type(parsed) is dict and canonical_json(parsed) == self.evidence_json and digest_payload(parsed) == self.evidence_digest)
            value = cast(dict[str, Any], parsed)
            _require(set(value) == {"schema_version", "stock_order_id", "issue_plan", "valuation_document", "valuation_lines", "consumptions", "posting_effect"}
                and value["schema_version"] == ORIGINAL_COST_EVIDENCE_VERSION
                and type(value["stock_order_id"]) is str and bool(value["stock_order_id"]))
            issue, document, lines, consumptions = value["issue_plan"], value["valuation_document"], value["valuation_lines"], value["consumptions"]
            _require(type(issue) is dict and type(document) is dict and type(lines) is list and len(lines) == 1
                and type(lines[0]) is dict and type(consumptions) is list and 1 <= len(consumptions) <= 32)
            _require(issue["schema_version"] == "stock-sales-issue-v2" and issue["cost_admission_policy"] == STOCK_RESTITUTED_COST_POLICY
                and type(issue["restitution_cost_snapshot"]) is dict
                and issue["restitution_cost_snapshot"]["schema_version"] == "inventory-transfer-cost-v3")
            total = issue["total_cost_minor"]
            _require(type(total) is int and 0 <= total <= 9_000_000_000_000_000_000
                and document["status"] == "Approved" and type(document["total_value_minor"]) is int and document["total_value_minor"] == total
                and lines[0]["flow_direction"] == "Outbound" and type(lines[0]["value_minor"]) is int and lines[0]["value_minor"] == total
                and type(lines[0]["quantity_scaled"]) is int and lines[0]["quantity_scaled"] > 0
                and type(issue["allocations"]) is list and len(issue["allocations"]) == len(consumptions))
            for allocation, consumption in zip(issue["allocations"], consumptions, strict=True):
                _require(type(allocation) is dict and type(consumption) is dict)
                _require(all(type(allocation[key]) is int for key in ("quantity_scaled", "value_minor"))
                    and all(type(consumption[key]) is int for key in ("quantity_scaled", "value_minor"))
                    and allocation["quantity_scaled"] > 0 and allocation["value_minor"] >= 0)
                _require(allocation["cost_layer_id"] == consumption["cost_layer_id"]
                    and allocation["quantity_scaled"] == consumption["quantity_scaled"] and allocation["value_minor"] == consumption["value_minor"]
                    and consumption["valuation_line_id"] == lines[0]["id"])
            _require(sum(row["value_minor"] for row in consumptions) == total
                and sum(row["quantity_scaled"] for row in consumptions) == lines[0]["quantity_scaled"]
                and len({row["id"] for row in consumptions}) == len(consumptions)
                and len({row["cost_layer_id"] for row in consumptions}) == len(consumptions))
            effect = value["posting_effect"]
            if total == 0:
                _require(effect is None and document["finance_entry_id"] is None and issue["entry_id"] is None)
            else:
                _require(type(effect) is dict and effect["entry_id"] == document["finance_entry_id"] == issue["entry_id"]
                    and validation_digest(effect["snapshot_json"]) == effect["validation_digest"]
                    and sum(line["debit_minor"] for line in effect["snapshot_json"]["lines"]) == total)
            return value
        except (KeyError, TypeError, ValueError, RecursionError) as exc:
            raise FinancePostingError("partial_return_cost_evidence_invalid", "Original restituted-cost evidence refused.") from exc


def restituted_source_money_context(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Finite READ sensitivity for the explicit factual source-v2 contract.

    Absent COGS is admitted only by a complete zero-total factual proof. All
    retained prices, issue amounts, real snapshots and policy carriers still
    contribute to the original captured-policy authorization ceiling.
    """
    try:
        source = plan["source_snapshot"]
        _require(isinstance(source, Mapping) and "cost_admission" in source)
        proof = OriginalRestitutedCostEvidence(canonical_json(source["cost_admission"]), digest_payload(source["cost_admission"])).snapshot()
        stock, invoice, revenue = source["stock"], source["invoice"], source["revenue"]
        _require(proof["stock_order_id"] == stock["id"] and proof["issue_plan"] == stock["issue_plan"]
            and proof["consumptions"] == source["consumptions"] and proof["posting_effect"] == source["cogs"])
        fields = ("currency_code", "currency_precision", "currency_rounding_policy", "currency_registry_version", "currency_registry_digest")
        policy = tuple(invoice[key] for key in fields)
        _require(type(policy[1]) is int and 0 <= policy[1] <= 18
            and all(type(value) is str and bool(value) for index, value in enumerate(policy) if index != 1))
        amounts: list[int] = []

        def money(value: Any) -> None:
            _require(type(value) is int and 0 <= value <= 9_000_000_000_000_000_000)
            amounts.append(value)

        def affinity(value: Mapping[str, Any], *, compact: bool = False) -> None:
            keys = ("currency_code", "precision", "rounding_policy", "registry_version", "registry_digest") if compact else fields
            actual = tuple(value[key] for key in keys)
            _require(all(type(left) is type(right) and left == right for left, right in zip(actual, policy, strict=True)))

        def snapshot(value: Mapping[str, Any]) -> None:
            affinity(value["entry"])
            _require(type(value["lines"]) is list and 1 <= len(value["lines"]) <= 1000)
            for line in value["lines"]:
                money(line["debit_minor"])
                money(line["credit_minor"])

        _require(plan["currency_code"] == policy[0] and type(plan["currency_precision"]) is int and plan["currency_precision"] == policy[1])
        for name in ("amount_minor", "credit_minor", "receivable_released_minor", "refund_entitlement_delta_minor", "cogs_restored_minor"):
            if name in plan:
                money(plan[name])
        entries = plan.get("entries", [])
        _require(type(entries) is list and len(entries) <= 2)
        for part in entries:
            snapshot(part["snapshot"])
        for name in ("subtotal_minor", "tax_minor", "total_minor"):
            money(invoice[name])
        money(source["allocated_minor"])
        money(stock["total_minor"])
        _require(stock["currency_code"] == stock["source"]["currency_code"] == policy[0])
        affinity(stock["source"]["monetary_policy"], compact=True)
        affinity(stock["issue_plan"]["currency_policy"], compact=True)
        for name in ("unit_price_minor", "net_unit_price_minor", "tax_minor", "total_minor"):
            money(stock["source"][name])
        money(stock["issue_plan"]["total_cost_minor"])
        for allocation in stock["issue_plan"]["allocations"]:
            money(allocation["remaining_value_minor"])
            money(allocation["value_minor"])
        for consumption in proof["consumptions"]:
            money(consumption["value_minor"])
        for effect in (revenue, source["cogs"]):
            if effect is not None:
                affinity(effect)
                snapshot(effect["snapshot_json"])
        return {**plan, "amount_minor": max(amounts), "currency_precision": policy[1]}
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise FinancePostingError("partial_return_cost_evidence_invalid", "Original restituted-cost monetary context refused.") from exc
