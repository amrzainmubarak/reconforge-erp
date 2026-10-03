"""Closed reviewed single-receipt plans and complete unused inverses."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Never, TypedDict, cast

from reconforge.domain.finance_posting import (
    FinancePostingError,
    PostingActor,
    canonical_json,
    digest_payload,
    make_entry_snapshot,
    validation_digest,
)
from reconforge.domain.quantities import scaled_integer_text

PLAN_VERSION = "inventory-receipt-plan-v1"
REVIEW_VERSION = "inventory-receipt-review-v1"
EFFECT_VERSION = "inventory-receipt-effect-v1"
MAX_RECEIPT_BYTES = 65_536
MAX_VALUE = 9_000_000_000_000_000_000
ReceiptOperation = Literal["Receipt", "FullReceiptReversal"]
SCOPE_KEYS = {"workspace_id", "organization_id", "legal_entity_id", "organization_code", "entity_code"}
SOURCE_KEYS = {"number", "posting_date", "period_id", "item_id", "uom_id", "location_id", "quantity_scaled", "quantity_precision", "quantity_text", "total_value_minor"}
MAPPING_KEYS = {"policy_id", "costing_method", "currency_code", "journal_id", "inventory_account_id", "receipt_clearing_account_id", "cogs_account_id", "adjustment_account_id"}
POLICY_KEYS = {"currency_code", "currency_precision", "currency_rounding_policy", "currency_registry_version", "currency_registry_digest"}
ORIGINAL_KEYS = {"plan_id", "posting_effect_id", "valuation_document_id", "valuation_line_id", "cost_layer_id"}
ARTIFACT_TAGS = {"movement_id": "MOV", "movement_line_id": "MOVL", "valuation_document_id": "VAL", "input_cost_id": "COST", "valuation_line_id": "VALL", "cost_layer_id": "LAY", "valuation_reversal_id": "REV", "reversal_effect_id": "REVE", "finance_entry_id": "GLE", "finance_line_1_id": "GLL1", "finance_line_2_id": "GLL2", "posting_effect_id": "PST"}
ARTIFACT_KEYS = {*ARTIFACT_TAGS, "movement_number", "valuation_number", "finance_entry_number"}
PREPARE_PERMISSIONS = frozenset({"inventory.manage", "inventory.valuation.manage", "finance_core.manage"})
REVIEW_PERMISSIONS = frozenset({"inventory.post", "inventory.valuation.approve", "finance_core.validate"})
COMMIT_PERMISSIONS = frozenset({"inventory.post", "inventory.valuation.approve", "finance_core.post"})
READ_PERMISSIONS = frozenset({"inventory.read", "finance_core.read"})
FINANCE_EFFECT_KEYS = {"id", "workspace_id", "organization_id", "legal_entity_id", "entry_id", "source_kind", "source_id", "purpose",
                       "reverses_effect_id", "validation_digest", "validation_contract_version", *POLICY_KEYS,
                       "snapshot", "posted_actor_id", "posted_at", "reason", "audit_event_id", "outbox_event_id"}


class InventoryReceiptPostingError(FinancePostingError):
    """A safe closed-source, ownership or command failure."""


@dataclass(frozen=True, kw_only=True)
class ReceiptPreparation:
    receipt_number: str
    posting_date: str
    period_id: str
    item_code: str
    location_code: str
    quantity: str
    total_value_minor: int
    policy_code: str
    organization_code: str
    entity_code: str
    reason: str
    workspace: str = "default"


@dataclass(frozen=True, kw_only=True)
class ReceiptReversalPreparation:
    original_plan_id: str
    reversal_number: str
    posting_date: str
    period_id: str
    reason: str


class ReceiptPlan(TypedDict):
    contract_version: str
    plan_id: str
    plan_version: int
    operation: ReceiptOperation
    prepared_at: str
    reason: str
    preparer: dict[str, str]
    scope: dict[str, str]
    source: dict[str, Any]
    mapping: dict[str, Any]
    mapping_digest: str
    currency_policy: dict[str, Any]
    artifacts: dict[str, str | None]
    original: dict[str, str] | None
    finance_snapshot: dict[str, Any]
    finance_validation_digest: str
    plan_digest: str
    preparation_audit_event_id: str
    preparation_outbox_event_id: str


class ReceiptReview(TypedDict):
    contract_version: str
    review_id: str
    plan_id: str
    plan_version: int
    plan_digest: str
    finance_validation_digest: str
    reviewer: dict[str, str]
    reviewed_at: str
    reason: str
    review_digest: str
    audit_event_id: str
    outbox_event_id: str


class ReceiptEffect(TypedDict):
    contract_version: str
    plan_id: str
    operation: ReceiptOperation
    plan_digest: str
    review_id: str
    review_digest: str
    source_kind: str
    purpose: str
    source_id: str
    movement_id: str
    valuation_document_id: str | None
    valuation_reversal_id: str | None
    cost_layer_id: str
    entry_id: str
    effect_id: str
    reverses_effect_id: str | None
    posted_actor_id: str
    posted_at: str
    audit_event_id: str
    outbox_event_id: str
    finance_effect: dict[str, Any]
    effect_digest: str


class ReceiptPlanView(TypedDict):
    plan: ReceiptPlan
    review: ReceiptReview | None
    effect: ReceiptEffect | None


def fail(message: str, code: str = "inventory_receipt_evidence_invalid") -> Never:
    raise InventoryReceiptPostingError(code, message)


def exact_text(value: object, *, maximum: int = 160) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        fail("Receipt evidence requires bounded canonical printable text.")
    return cast(str, value)


def exact_int(value: object, *, minimum: int = 1, maximum: int = MAX_VALUE) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        fail("Receipt evidence requires bounded exact integers.")
    return cast(int, value)


def closed(value: object, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        fail("Receipt evidence has missing or unknown fields.")
    return dict(cast(Mapping[str, Any], value))


def exact_date(value: object) -> str:
    selected = exact_text(value, maximum=10)
    try:
        if date.fromisoformat(selected).isoformat() != selected:
            raise ValueError
    except ValueError as exc:
        raise InventoryReceiptPostingError("inventory_receipt_evidence_invalid", "Receipt business date must be YYYY-MM-DD.") from exc
    return selected


def _timestamp(value: object) -> None:
    selected = exact_text(value, maximum=40)
    try:
        parsed = datetime.fromisoformat(selected.replace("Z", "+00:00"))
        offset = parsed.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError
    except ValueError as exc:
        raise InventoryReceiptPostingError("inventory_receipt_evidence_invalid", "Receipt evidence requires a UTC timestamp.") from exc


def source_plan_id(scope: Mapping[str, str], source_number: str) -> str:
    components = [PLAN_VERSION, *(scope[key] for key in ("workspace_id", "organization_id", "legal_entity_id")), source_number]
    return "IRP1-PLAN-" + digest_payload(components)[:32]


def artifact_id(plan_id: str, tag: str) -> str:
    if tag not in {*ARTIFACT_TAGS.values(), "REVIEW"}:
        fail("Unsupported receipt artifact identity.")
    return f"IRP1-{tag}-" + hashlib.sha256(plan_id.encode("utf-8")).hexdigest()[:32]


def artifacts_for(plan_id: str, operation: ReceiptOperation, original: Mapping[str, str] | None) -> dict[str, str | None]:
    artifacts: dict[str, str | None] = {key: artifact_id(plan_id, tag) for key, tag in ARTIFACT_TAGS.items()}
    if operation == "Receipt":
        artifacts.update(valuation_reversal_id=None, reversal_effect_id=None)
        valuation_number = artifact_id(plan_id, "VAL").upper()
    elif operation == "FullReceiptReversal" and original is not None:
        artifacts.update(valuation_document_id=None, input_cost_id=None, valuation_line_id=None, cost_layer_id=original["cost_layer_id"])
        valuation_number = artifact_id(plan_id, "REV").upper()
    else:
        fail("Receipt operation and original source disagree.")
    artifacts.update(movement_number=artifact_id(plan_id, "MOV").upper(), valuation_number=valuation_number,
                     finance_entry_number=artifact_id(plan_id, "GLE").upper())
    return artifacts


def _plan_digest(plan: Mapping[str, Any]) -> str:
    return digest_payload({key: value for key, value in plan.items() if key not in {"plan_digest", "preparation_audit_event_id", "preparation_outbox_event_id"}})


def _review_digest(review: Mapping[str, Any]) -> str:
    return digest_payload({key: value for key, value in review.items() if key not in {"review_digest", "audit_event_id", "outbox_event_id"}})


def planned_finance_snapshot(plan: Mapping[str, Any]) -> dict[str, Any]:
    source, scope, mapping, artifacts = (plan[key] for key in ("source", "scope", "mapping", "artifacts"))
    inverse = plan["operation"] == "FullReceiptReversal"
    amount = source["total_value_minor"]
    entry = {"id": artifacts["finance_entry_id"], "workspace_id": scope["workspace_id"], "organization_id": scope["organization_id"],
             "legal_entity_id": scope["legal_entity_id"], "journal_id": mapping["journal_id"], "period_id": source["period_id"],
             "entry_number": artifacts["finance_entry_number"], "posting_date": source["posting_date"], "description": plan["reason"],
             "external_reference": plan["plan_id"], "source_type": "Generated", **plan["currency_policy"],
             "preparer_actor_id": plan["preparer"]["user_id"], "reverses_posting_id": plan["original"]["posting_effect_id"] if inverse else None}
    lines = [{"line_number": 1, "account_id": mapping["inventory_account_id"], "description": plan["reason"],
              "debit_minor": 0 if inverse else amount, "credit_minor": amount if inverse else 0, "dimensions": {}},
             {"line_number": 2, "account_id": mapping["receipt_clearing_account_id"], "description": plan["reason"],
              "debit_minor": amount if inverse else 0, "credit_minor": 0 if inverse else amount, "dimensions": {}}]
    return make_entry_snapshot(entry, lines)


def verify_plan(value: object) -> ReceiptPlan:
    plan = closed(value, set(ReceiptPlan.__annotations__))
    try:
        if plan["contract_version"] != PLAN_VERSION or type(plan["plan_version"]) is not int or plan["plan_version"] != 1 or plan["operation"] not in {"Receipt", "FullReceiptReversal"}:
            fail("Unsupported receipt plan contract.")
        scope = closed(plan["scope"], SCOPE_KEYS)
        for item in scope.values():
            exact_text(item)
        preparer = closed(plan["preparer"], {"user_id", "username"})
        for item in preparer.values():
            exact_text(item)
        _timestamp(plan["prepared_at"])
        exact_text(plan["reason"], maximum=500)
        source = closed(plan["source"], SOURCE_KEYS)
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]{0,63}", exact_text(source["number"], maximum=64)):
            fail("Receipt source number must retain its normalized spelling.")
        exact_date(source["posting_date"])
        for key in ("period_id", "item_id", "uom_id", "location_id"):
            exact_text(source[key])
        precision = exact_int(source["quantity_precision"], minimum=0, maximum=6)
        quantity = exact_int(source["quantity_scaled"])
        exact_int(source["total_value_minor"])
        if source["quantity_text"] != scaled_integer_text(quantity, precision):
            fail("Receipt scaled and textual quantities disagree.")
        mapping = closed(plan["mapping"], MAPPING_KEYS)
        for key in MAPPING_KEYS:
            exact_text(mapping[key])
        if mapping["costing_method"] != "FIFO" or mapping["inventory_account_id"] == mapping["receipt_clearing_account_id"] or plan["mapping_digest"] != digest_payload(mapping):
            fail("Receipt valuation mapping is invalid.")
        policy = closed(plan["currency_policy"], POLICY_KEYS)
        exact_int(policy["currency_precision"], minimum=0, maximum=8)
        if not re.fullmatch("[A-Z]{3}", exact_text(policy["currency_code"], maximum=3)) or mapping["currency_code"] != policy["currency_code"] or policy["currency_rounding_policy"] != "ROUND_HALF_UP":
            fail("Receipt monetary policy is invalid.")
        exact_text(policy["currency_registry_version"])
        if not re.fullmatch("[0-9a-f]{64}", exact_text(policy["currency_registry_digest"], maximum=64)):
            fail("Receipt monetary policy digest is invalid.")
        original = plan["original"]
        if plan["operation"] == "Receipt":
            if original is not None:
                fail("Receipt cannot carry inverse references.")
        else:
            original = closed(original, ORIGINAL_KEYS)
            for item in original.values():
                exact_text(item)
        if plan["plan_id"] != source_plan_id(scope, source["number"]):
            fail("Receipt source identity is not canonical.")
        if closed(plan["artifacts"], ARTIFACT_KEYS) != artifacts_for(plan["plan_id"], plan["operation"], original):
            fail("Receipt output identities are not canonical.")
        expected = planned_finance_snapshot(plan)
        if canonical_json(plan["finance_snapshot"]) != canonical_json(expected) or plan["finance_validation_digest"] != validation_digest(expected):
            fail("Receipt Finance content differs from the reviewed source plan.")
        if plan["plan_digest"] != _plan_digest(plan):
            fail("Receipt plan digest does not match its content.")
        exact_text(plan["preparation_audit_event_id"])
        exact_text(plan["preparation_outbox_event_id"])
        if len(canonical_json(plan).encode("utf-8")) > MAX_RECEIPT_BYTES:
            fail("Receipt plan exceeds its evidence budget.")
    except (KeyError, TypeError, AttributeError) as exc:
        raise InventoryReceiptPostingError("inventory_receipt_evidence_invalid", "Receipt plan contains malformed content.") from exc
    return cast(ReceiptPlan, plan)


def make_plan(*, operation: ReceiptOperation, scope: Mapping[str, str], source: Mapping[str, Any], mapping: Mapping[str, Any],
              currency_policy: Mapping[str, Any], actor: PostingActor, prepared_at: str, reason: str,
              audit_event_id: str, outbox_event_id: str, original: Mapping[str, str] | None = None) -> ReceiptPlan:
    plan_id = source_plan_id(scope, source["number"])
    plan: dict[str, Any] = {"contract_version": PLAN_VERSION, "plan_id": plan_id, "plan_version": 1, "operation": operation,
                            "prepared_at": prepared_at, "reason": reason, "preparer": {"user_id": actor.user_id, "username": actor.username},
                            "scope": dict(scope), "source": dict(source), "mapping": dict(mapping), "mapping_digest": digest_payload(mapping),
                            "currency_policy": dict(currency_policy), "artifacts": artifacts_for(plan_id, operation, original),
                            "original": dict(original) if original is not None else None,
                            "preparation_audit_event_id": audit_event_id, "preparation_outbox_event_id": outbox_event_id}
    plan["finance_snapshot"] = planned_finance_snapshot(plan)
    plan["finance_validation_digest"] = validation_digest(plan["finance_snapshot"])
    plan["plan_digest"] = _plan_digest(plan)
    return verify_plan(plan)


def verify_review(value: object, plan: ReceiptPlan) -> ReceiptReview:
    review = closed(value, set(ReceiptReview.__annotations__))
    reviewer = closed(review["reviewer"], {"user_id", "username"})
    for item in reviewer.values():
        exact_text(item)
    if (review["contract_version"] != REVIEW_VERSION or review["review_id"] != artifact_id(plan["plan_id"], "REVIEW")
            or any(review[key] != plan[key] for key in ("plan_id", "plan_digest", "finance_validation_digest"))
            or type(review["plan_version"]) is not int or review["plan_version"] != 1
            or reviewer["user_id"] == plan["preparer"]["user_id"]):
        fail("Receipt review does not independently bind its source plan.")
    _timestamp(review["reviewed_at"])
    exact_text(review["reason"], maximum=500)
    for key in ("audit_event_id", "outbox_event_id"):
        exact_text(review[key])
    if review["review_digest"] != _review_digest(review):
        fail("Receipt review digest does not match its content.")
    if len(canonical_json(review).encode("utf-8")) > MAX_RECEIPT_BYTES:
        fail("Receipt review exceeds its evidence budget.")
    return cast(ReceiptReview, review)


def make_review(plan: ReceiptPlan, *, actor: PostingActor, reviewed_at: str, reason: str, audit_event_id: str, outbox_event_id: str) -> ReceiptReview:
    review: dict[str, Any] = {"contract_version": REVIEW_VERSION, "review_id": artifact_id(plan["plan_id"], "REVIEW"),
                              "plan_id": plan["plan_id"], "plan_version": 1, "plan_digest": plan["plan_digest"],
                              "finance_validation_digest": plan["finance_validation_digest"],
                              "reviewer": {"user_id": actor.user_id, "username": actor.username}, "reviewed_at": reviewed_at,
                              "reason": reason, "audit_event_id": audit_event_id, "outbox_event_id": outbox_event_id}
    review["review_digest"] = _review_digest(review)
    return verify_review(review, plan)


def verify_inverse(plan: ReceiptPlan, original: ReceiptPlan) -> None:
    verify_plan(plan)
    verify_plan(original)
    if (plan["operation"] != "FullReceiptReversal" or original["operation"] != "Receipt"
            or plan["scope"] != original["scope"] or plan["mapping"] != original["mapping"]
            or plan["currency_policy"] != original["currency_policy"]
            or any(plan["source"][key] != original["source"][key] for key in ("item_id", "uom_id", "location_id", "quantity_scaled", "quantity_precision", "quantity_text", "total_value_minor"))
            or plan["original"] != {"plan_id": original["plan_id"], "posting_effect_id": original["artifacts"]["posting_effect_id"],
                                    "valuation_document_id": original["artifacts"]["valuation_document_id"], "valuation_line_id": original["artifacts"]["valuation_line_id"],
                                    "cost_layer_id": original["artifacts"]["cost_layer_id"]}):
        fail("Receipt inverse must preserve the complete original physical and monetary source.")


def make_effect(plan: ReceiptPlan, review: ReceiptReview, finance_effect: Mapping[str, Any], *, audit_event_id: str, outbox_event_id: str) -> ReceiptEffect:
    artifacts = plan["artifacts"]
    effect: dict[str, Any] = {"contract_version": EFFECT_VERSION, "plan_id": plan["plan_id"], "operation": plan["operation"],
                            "plan_digest": plan["plan_digest"], "review_id": review["review_id"], "review_digest": review["review_digest"],
                            "source_kind": "InventoryReceipt" if plan["operation"] == "Receipt" else "InventoryReceiptReversal",
                            "purpose": "operational_posting", "source_id": plan["plan_id"], "movement_id": artifacts["movement_id"],
                            "valuation_document_id": artifacts["valuation_document_id"], "valuation_reversal_id": artifacts["valuation_reversal_id"],
                            "cost_layer_id": artifacts["cost_layer_id"], "entry_id": artifacts["finance_entry_id"], "effect_id": artifacts["posting_effect_id"],
                            "reverses_effect_id": plan["original"]["posting_effect_id"] if plan["original"] else None,
                            "posted_actor_id": finance_effect["posted_actor_id"], "posted_at": finance_effect["posted_at"],
                            "audit_event_id": audit_event_id, "outbox_event_id": outbox_event_id, "finance_effect": dict(finance_effect)}
    effect["effect_digest"] = digest_payload(effect)
    return cast(ReceiptEffect, effect)


def verify_effect(value: object, plan: ReceiptPlan, review: ReceiptReview) -> ReceiptEffect:
    effect = closed(value, set(ReceiptEffect.__annotations__))
    verify_plan(plan)
    verify_review(review, plan)
    finance = closed(effect["finance_effect"], FINANCE_EFFECT_KEYS)
    try:
        for key in ("posted_actor_id", "audit_event_id", "outbox_event_id"):
            exact_text(effect[key])
            exact_text(finance[key])
        exact_text(finance["reason"], maximum=500)
        _timestamp(effect["posted_at"])
        expected = make_effect(plan, review, finance, audit_event_id=effect["audit_event_id"], outbox_event_id=effect["outbox_event_id"])
        if canonical_json(effect) != canonical_json(expected) or effect["posted_actor_id"] == plan["preparer"]["user_id"]:
            fail("Receipt effect differs from its reviewed source or violates independent posting.")
        for field, expected_value in {"id": effect["effect_id"], "entry_id": effect["entry_id"], "source_kind": effect["source_kind"],
                                     "source_id": plan["plan_id"], "purpose": "operational_posting", "reverses_effect_id": effect["reverses_effect_id"],
                                     "validation_digest": plan["finance_validation_digest"], "validation_contract_version": "finance-entry-review-v1",
                                     **{key: plan["scope"][key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
                                     **plan["currency_policy"]}.items():
            if type(finance.get(field)) is not type(expected_value) or finance.get(field) != expected_value:
                fail("Receipt Finance effect has contradictory source identity or policy.")
        if canonical_json(finance["snapshot"]) != canonical_json(plan["finance_snapshot"]):
            fail("Receipt Finance effect differs from the exact reviewed snapshot.")
        if len(canonical_json(effect).encode("utf-8")) > MAX_RECEIPT_BYTES:
            fail("Receipt effect exceeds its evidence budget.")
    except (KeyError, TypeError, AttributeError) as exc:
        raise InventoryReceiptPostingError("inventory_receipt_evidence_invalid", "Receipt effect contains malformed content.") from exc
    return cast(ReceiptEffect, effect)
