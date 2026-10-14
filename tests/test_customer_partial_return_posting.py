"""Content-only correction contracts, with independent original Fraction vectors."""

from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from reconforge.domain.customer_partial_return_posting import (
    PARTIAL_RETURN_TEMPLATE_JSON_POLICY,
    PartialReturnAccountRoles,
    PartialReturnCorrectionTemplate,
    PartialReturnPostingContract,
    PartialReturnPostingIntent,
    build_partial_return_posting_contract,
    verify_partial_return_posting_contract,
)
from reconforge.domain.customer_partial_returns import (
    OriginalPostingEvidence,
    PartialReturnHistory,
    apply_partial_return,
    collect_partial_return,
    prepare_partial_return,
)
from reconforge.domain.finance_posting import FinancePostingError, canonical_json, validation_digest
from reconforge.io.structured import StructuredDocumentError
from tests.test_customer_partial_return_design import DESIGN, derive
from tests.test_customer_partial_returns_domain import source_for

INTENT = PartialReturnPostingIntent("REQUESTED-PERIOD", "2026-10-14", "Original partial merchandise correction")


def roles_for(source: Any) -> PartialReturnAccountRoles:
    return PartialReturnAccountRoles(source.scope, source.fingerprint, source.currency_policy,
        "AR", "REVENUE", "INVENTORY", "COGS", "REFUND", "Liability")


def basis() -> tuple[Any, PartialReturnAccountRoles, PartialReturnPostingContract]:
    source = source_for(DESIGN["cases"][0])
    plan = prepare_partial_return(PartialReturnHistory(source), DESIGN["cases"][0]["steps"][0]["quantity_scaled"])
    roles = roles_for(source)
    return plan, roles, build_partial_return_posting_contract(plan, roles=roles, intent=INTENT)


def vector(template: PartialReturnCorrectionTemplate) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in template.payload()["lines"]:
        assert type(line["debit_minor"]) is type(line["credit_minor"]) is int
        result[line["account_id"]] = result.get(line["account_id"], 0) + line["debit_minor"] - line["credit_minor"]
    return result


@pytest.mark.parametrize("case", DESIGN["cases"], ids=lambda case: case["id"])
def test_each_original_portion_derives_independent_balanced_corrections_and_preserves_all_pins(case: dict[str, Any]) -> None:
    original_case = deepcopy(case)
    source = source_for(case)
    original_source = (source.fingerprint, source.original_cogs.snapshot_json, source.original_revenue.snapshot_json)
    history = PartialReturnHistory(source)
    original_history = history
    oracle = derive(case)  # Existing standalone stdlib Fraction oracle, not the ERP derivation.
    for step, expected in zip(case["steps"], oracle, strict=True):
        if step["collect_before_minor"]:
            history = collect_partial_return(history, step["collect_before_minor"])
        plan = prepare_partial_return(history, step["quantity_scaled"])
        roles = roles_for(source)
        contract = build_partial_return_posting_contract(plan, roles=roles, intent=INTENT)
        verify_partial_return_posting_contract(contract, plan, roles, INTENT)
        credit = Fraction(case["gross_minor"] * step["quantity_scaled"], case["quantity_scaled"])
        assert credit.denominator == 1 and credit == expected["credit_minor"]
        expected_revenue = {"REVENUE": int(credit)}
        if expected["ar_release_minor"]:
            expected_revenue["AR"] = -expected["ar_release_minor"]
        if expected["refund_delta_minor"]:
            expected_revenue["REFUND"] = -expected["refund_delta_minor"]
        assert vector(contract.revenue_credit) == expected_revenue
        assert vector(contract.cost_restoration) == {"INVENTORY": expected["cost_minor"], "COGS": -expected["cost_minor"]}
        for template, original in ((contract.revenue_credit, source.original_revenue), (contract.cost_restoration, source.original_cogs)):
            payload = template.payload()
            snapshot = original.snapshot()
            lines = payload["lines"]
            assert sum(line["debit_minor"] for line in lines) == sum(line["credit_minor"] for line in lines) > 0
            assert all((line["debit_minor"] > 0) != (line["credit_minor"] > 0) for line in lines)
            assert [line["line_number"] for line in lines] == list(range(1, len(lines) + 1))
            assert payload["journal_id"] == snapshot["entry"]["journal_id"]
            assert payload["original_posting_effect_id"] == original.posting_effect_id
            assert payload["original_entry_id"] == original.entry_id
            assert payload["original_validation_digest"] == original.validation_digest
            assert payload["currency_policy"] == {key: snapshot["entry"][key] for key in payload["currency_policy"]}
            assert payload["portions"] == plan.payload()["portions"] or canonical_json(payload["portions"]) == canonical_json(plan.payload()["portions"])
            assert payload["posting_intent"] == INTENT.payload() and payload["reverses_posting_id"] is None
            assert payload["postable"] is False
            assert all(payload[key] is True for key in ("requires_native_participant", "requires_current_authorization", "requires_three_person_approval"))
            assert not {"entry_id", "entry_number", "preparer_actor_id", "validator_actor_id", "posted_actor_id"} & set(payload)
        revenue_lines, cost_lines = contract.revenue_credit.payload()["lines"], contract.cost_restoration.payload()["lines"]
        ar_dimensions = source.original_revenue.snapshot()["lines"][0]["dimensions"]
        assert revenue_lines[0]["dimensions"] == source.original_revenue.snapshot()["lines"][1]["dimensions"]
        assert all(line["dimensions"] == ar_dimensions for line in revenue_lines[1:])
        assert cost_lines[0]["dimensions"] == source.original_cogs.snapshot()["lines"][1]["dimensions"]
        assert cost_lines[1]["dimensions"] == source.original_cogs.snapshot()["lines"][0]["dimensions"]
        history = apply_partial_return(history, plan)
    assert case == original_case and original_history.events == ()
    assert original_source == (source.fingerprint, source.original_cogs.snapshot_json, source.original_revenue.snapshot_json)


@pytest.mark.parametrize("field,value", [
    ("receivable_account_id", "OTHER-AR"), ("revenue_account_id", "OTHER-REVENUE"),
    ("inventory_account_id", "OTHER-INVENTORY"), ("cogs_account_id", "OTHER-COGS"),
    ("refund_liability_account_id", "AR"), ("refund_liability_account_id", True),
    ("refund_liability_account_type", "Expense"), ("source_fingerprint", "f" * 64),
])
def test_native_role_pins_refuse_wrong_accounts_nature_source_or_identity(field: str, value: Any) -> None:
    plan, roles, _ = basis()
    with pytest.raises(FinancePostingError):
        build_partial_return_posting_contract(plan, roles=replace(roles, **{field: value}), intent=INTENT)


@pytest.mark.parametrize("policy_field,value", [("currency_code", "EUR"), ("precision", True),
    ("precision", 3), ("registry_digest", "e" * 64), ("registry_version", "unapproved-version")])
def test_role_policy_cannot_reinterpret_captured_original_money(policy_field: str, value: Any) -> None:
    plan, roles, _ = basis()
    with pytest.raises(FinancePostingError):
        build_partial_return_posting_contract(plan,
            roles=replace(roles, currency_policy=replace(roles.currency_policy, **{policy_field: value})), intent=INTENT)


def test_same_balanced_original_amount_with_swapped_account_roles_is_not_an_original_pin() -> None:
    source = source_for(DESIGN["cases"][0])
    for field in ("original_revenue", "original_cogs"):
        evidence = getattr(source, field)
        snapshot = evidence.snapshot()
        snapshot["lines"][0]["account_id"], snapshot["lines"][1]["account_id"] = snapshot["lines"][1]["account_id"], snapshot["lines"][0]["account_id"]
        forged = OriginalPostingEvidence(evidence.posting_effect_id, evidence.scope, canonical_json(snapshot), validation_digest(snapshot))
        changed = replace(source, original_revenue=forged) if field == "original_revenue" else replace(source, original_cogs=forged)
        plan = prepare_partial_return(PartialReturnHistory(changed), DESIGN["cases"][0]["steps"][0]["quantity_scaled"])
        with pytest.raises(FinancePostingError):
            build_partial_return_posting_contract(plan, roles=roles_for(changed), intent=INTENT)
    assert source.original_revenue.snapshot()["lines"][0]["account_id"] == "AR"


@pytest.mark.parametrize("field,value", [("credit_minor", 1), ("cogs_restored_minor", 1),
    ("receivable_released_minor", 0), ("refund_entitlement_delta_minor", 1),
    ("expected_version", 1), ("source_fingerprint", "d" * 64), ("history_fingerprint", "c" * 64)])
def test_caller_plan_tampering_is_recomputed_before_any_template_is_emitted(field: str, value: Any) -> None:
    plan, roles, _ = basis()
    with pytest.raises(FinancePostingError):
        build_partial_return_posting_contract(replace(plan, **{field: value}), roles=roles, intent=INTENT)


@pytest.mark.parametrize("field,value", [("scope", None), ("scope", {}), ("currency_policy", None),
    ("currency_policy", {}), ("posting_intent", None), ("posting_intent", {}),
    ("portions", []), ("portions", [None]), ("portions", [{}]), ("lines", []),
    ("postable", True), ("postable", 0), ("requires_three_person_approval", 1),
    ("reverses_posting_id", "FULL-INVERSE"), ("purpose", ["RevenueCredit"])])
def test_malformed_nested_template_is_refused_by_public_constructor(field: str, value: Any) -> None:
    _, _, contract = basis()
    payload = contract.revenue_credit.payload()
    payload[field] = value
    with pytest.raises(FinancePostingError):
        PartialReturnCorrectionTemplate(canonical_json(payload))


@pytest.mark.parametrize("change", ["account", "currency", "dimensions", "journal", "effect", "portion", "balanced_amount"])
def test_balanced_but_wrong_template_content_fails_original_recomputation(change: str) -> None:
    plan, roles, contract = basis()
    payload = contract.revenue_credit.payload()
    if change == "account":
        payload["lines"][0]["account_id"] = "OTHER-INCOME"
    elif change == "currency":
        payload["currency_policy"]["currency_code"] = "EUR"
    elif change == "dimensions":
        payload["lines"][0]["dimensions"] = {"PROJECT": "OTHER-PROJECT"}
    elif change == "journal":
        payload["journal_id"] = "OTHER-JOURNAL"
    elif change == "effect":
        payload["original_posting_effect_id"] = "OTHER-ORIGINAL-EFFECT"
    elif change == "portion":
        payload["portions"][0]["offset_quantity_scaled"] += 1
    else:
        payload["lines"][0]["debit_minor"] += 1
        payload["lines"][1]["credit_minor"] += 1
    changed = PartialReturnCorrectionTemplate(canonical_json(payload))
    with pytest.raises(FinancePostingError):
        verify_partial_return_posting_contract(PartialReturnPostingContract(changed, contract.cost_restoration), plan, roles, INTENT)


def test_balanced_cross_source_component_swap_is_not_one_source_owned_contract() -> None:
    plan, roles, contract = basis()
    other_case = deepcopy(DESIGN["cases"][0])
    other_case["collected_minor"] = 1
    other_source = source_for(other_case)
    other_plan = prepare_partial_return(PartialReturnHistory(other_source), plan.quantity_scaled)
    other = build_partial_return_posting_contract(other_plan, roles=roles_for(other_source), intent=INTENT)
    with pytest.raises(FinancePostingError):
        PartialReturnPostingContract(contract.revenue_credit, other.cost_restoration)
    with pytest.raises(FinancePostingError):
        build_partial_return_posting_contract(plan, roles=replace(roles, scope=replace(roles.scope, legal_entity_id="OTHER-ENTITY")), intent=INTENT)


@pytest.mark.parametrize("field,value", [("credit_minor", 0), ("credit_minor", True), ("credit_minor", 1.5),
    ("cogs_restored_minor", 0), ("cogs_restored_minor", False), ("cogs_restored_minor", 1.5)])
def test_zero_bool_or_noninteger_portions_never_create_a_zero_or_fractional_effect(field: str, value: Any) -> None:
    plan, roles, _ = basis()
    with pytest.raises(FinancePostingError):
        build_partial_return_posting_contract(replace(plan, **{field: value}), roles=roles, intent=INTENT)


def test_accessors_and_requested_period_never_mutate_or_approve_original_evidence() -> None:
    plan, roles, contract = basis()
    original = (plan.source.original_revenue.snapshot_json, plan.source.original_cogs.snapshot_json, contract.fingerprint)
    mutable = contract.payload()
    mutable["templates"][0]["lines"][0]["dimensions"]["FORGED"] = "FORGED"
    mutable["templates"][1]["posting_intent"]["period_id"] = "FORGED"
    assert original == (plan.source.original_revenue.snapshot_json, plan.source.original_cogs.snapshot_json, contract.fingerprint)
    assert plan.source.original_revenue.snapshot()["entry"]["period_id"] == "ORIGINAL-PERIOD"
    assert contract.payload()["postable"] is False
    immutable_template: Any = contract.revenue_credit
    with pytest.raises(FrozenInstanceError):
        immutable_template.template_json = "{}"
    with pytest.raises(FinancePostingError):
        build_partial_return_posting_contract(plan, roles=roles, intent=replace(INTENT, posting_date="20261014"))


def test_account_classification_is_an_explicit_native_fact_not_a_constructor_default() -> None:
    plan, roles, _ = basis()
    fields = {name: getattr(roles, name) for name in roles.__dataclass_fields__ if name != "refund_liability_account_type"}
    with pytest.raises(TypeError):
        PartialReturnAccountRoles(**fields)
    assert plan.source.scope == roles.scope and roles.refund_liability_account_type == "Liability"


@pytest.mark.parametrize("field,value", [
    ("position", True), ("position", 0), ("position", 33),
    ("offset_quantity_scaled", True), ("offset_quantity_scaled", -1),
    ("quantity_scaled", False), ("quantity_scaled", 0), ("quantity_scaled", 1.0),
    ("value_minor", True), ("value_minor", 0), ("value_minor", 1.0),
    ("original_consumption_id", None), ("cost_layer_id", " FORGED "),
])
def test_public_portions_refuse_invalid_quantity_identity_and_boolean_coercion(field: str, value: Any) -> None:
    _, _, contract = basis()
    payload = contract.revenue_credit.payload()
    payload["portions"][0][field] = value
    with pytest.raises(FinancePostingError):
        PartialReturnCorrectionTemplate(canonical_json(payload))


@pytest.mark.parametrize("kind", ["extra_scope", "extra_policy", "extra_intent", "extra_portion",
    "duplicate_consumption", "duplicate_layer", "too_many", "position_gap"])
def test_public_template_refuses_extra_fields_duplicate_links_and_unbounded_or_gapped_fifo(kind: str) -> None:
    _, _, contract = basis()
    payload = contract.revenue_credit.payload()
    if kind.startswith("extra_"):
        key = {"extra_scope": "scope", "extra_policy": "currency_policy", "extra_intent": "posting_intent"}.get(kind)
        if key:
            payload[key]["caller_field"] = "FORGED"
        else:
            payload["portions"][0]["caller_field"] = "FORGED"
    else:
        second = {**payload["portions"][0], "position": 2,
                  "original_consumption_id": "OTHER-CONSUMPTION", "cost_layer_id": "OTHER-LAYER"}
        if kind == "duplicate_consumption":
            second["original_consumption_id"] = payload["portions"][0]["original_consumption_id"]
        elif kind == "duplicate_layer":
            second["cost_layer_id"] = payload["portions"][0]["cost_layer_id"]
        elif kind == "position_gap":
            second["position"] = 3
        if kind == "too_many":
            payload["portions"] = [{**second, "position": index,
                "original_consumption_id": f"C{index}", "cost_layer_id": f"L{index}"} for index in range(1, 34)]
        else:
            payload["portions"].append(second)
    with pytest.raises(FinancePostingError):
        PartialReturnCorrectionTemplate(canonical_json(payload))


@pytest.mark.parametrize("kind", ["line_gap", "same_account", "unrequested_description", "amount_overflow"])
def test_public_template_refuses_balanced_lines_that_violate_its_finite_typed_contract(kind: str) -> None:
    _, _, contract = basis()
    payload = contract.revenue_credit.payload()
    if kind == "line_gap":
        payload["lines"][1]["line_number"] = 3
    elif kind == "same_account":
        payload["lines"][1]["account_id"] = payload["lines"][0]["account_id"]
    elif kind == "unrequested_description":
        payload["lines"][0]["description"] = "Caller injected a different intent"
    else:
        payload["lines"][0]["debit_minor"] = payload["lines"][1]["credit_minor"] = 9_000_000_000_000_000_001
    with pytest.raises(FinancePostingError):
        PartialReturnCorrectionTemplate(canonical_json(payload))


def test_maximum_fifo_portion_boundary_and_a_late_position_remain_admitted() -> None:
    case = deepcopy(DESIGN["cases"][0])
    case.update(quantity_scaled=32, gross_minor=80_000, net_unit_price_minor=2500, collected_minor=0,
                consumptions=[{"id": f"C{index}", "layer_id": f"L{index}",
                               "quantity_scaled": 1, "value_minor": 1200} for index in range(1, 33)])
    source = source_for(case)
    history = PartialReturnHistory(source)
    whole = prepare_partial_return(history, 32)
    contract = build_partial_return_posting_contract(whole, roles=roles_for(source), intent=INTENT)
    assert len(contract.cost_restoration.payload()["portions"]) == 32
    assert vector(contract.cost_restoration) == {"INVENTORY": 38_400, "COGS": -38_400}
    history = apply_partial_return(history, prepare_partial_return(history, 31))
    last = prepare_partial_return(history, 1)
    contract = build_partial_return_posting_contract(last, roles=roles_for(source), intent=INTENT)
    assert contract.revenue_credit.payload()["portions"][0]["position"] == 32
    assert vector(contract.cost_restoration) == {"INVENTORY": 1200, "COGS": -1200}


@pytest.mark.parametrize("optimized", [False, True], ids=["isolated", "isolated-optimized"])
def test_isolated_optimized_runtime_preserves_original_role_and_correction_refusals(optimized: bool) -> None:
    program = r'''
import json
import pathlib
import sys
from dataclasses import replace
sys.path.insert(0, sys.argv[1])
import reconforge.domain.customer_partial_return_posting as posting
from reconforge.domain.finance_posting import FinancePostingError, canonical_json
from tests.test_customer_partial_return_posting import basis, INTENT
expected_module = pathlib.Path(sys.argv[1]) / "reconforge/domain/customer_partial_return_posting.py"
if pathlib.Path(posting.__file__).resolve() != expected_module.resolve():
    raise RuntimeError("Isolated runtime imported a different correction source")
plan, roles, contract = basis()
def checked_vector(template):
    result = {}
    for line in template.payload()["lines"]:
        if type(line["debit_minor"]) is not int or type(line["credit_minor"]) is not int:
            raise RuntimeError("Original typed money changed")
        result[line["account_id"]] = result.get(line["account_id"], 0) + line["debit_minor"] - line["credit_minor"]
    return result
if checked_vector(contract.revenue_credit) != {"REVENUE": 2500, "AR": -2500}:
    raise RuntimeError("Independent revenue vector differs")
if checked_vector(contract.cost_restoration) != {"INVENTORY": 1200, "COGS": -1200}:
    raise RuntimeError("Independent original cost vector differs")
payload = contract.revenue_credit.payload()
wrong = {**payload, "lines": [dict(line) for line in payload["lines"]]}
wrong["lines"][0]["account_id"] = "FORGED-INCOME"
template = posting.PartialReturnCorrectionTemplate(canonical_json(wrong))
def refused(call):
    try:
        call()
    except FinancePostingError:
        return
    raise RuntimeError("An original correction guard disappeared")
checks = (
    lambda: posting.build_partial_return_posting_contract(replace(plan, credit_minor=True), roles=roles, intent=INTENT),
    lambda: posting.build_partial_return_posting_contract(replace(plan, cogs_restored_minor=0), roles=roles, intent=INTENT),
    lambda: posting.build_partial_return_posting_contract(plan, roles=replace(roles, revenue_account_id="FORGED"), intent=INTENT),
    lambda: replace(roles, refund_liability_account_type="Expense"),
    lambda: posting.PartialReturnCorrectionTemplate(canonical_json({**payload, "postable": True})),
    lambda: posting.PartialReturnCorrectionTemplate(canonical_json({**payload, "scope": None})),
    lambda: posting.verify_partial_return_posting_contract(posting.PartialReturnPostingContract(template, contract.cost_restoration), plan, roles, INTENT),
)
for check in checks:
    refused(check)
print(json.dumps({"schema_version": "partial-return-correction-isolated-guard-v1", "optimized": not __debug__,
                  "original_vectors_verified": True, "required_refusals": len(checks)}))
'''
    completed = subprocess.run(
        [sys.executable, "-I", *(["-O"] if optimized else []), "-c", program, str(Path(__file__).parents[1])],
        text=True, capture_output=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "schema_version": "partial-return-correction-isolated-guard-v1", "optimized": optimized,
        "original_vectors_verified": True, "required_refusals": 7,
    }


@pytest.mark.parametrize("kind", ["duplicate", "nonfinite", "fraction", "depth", "collection", "nodes", "scalar", "bytes"])
def test_correction_template_uses_shared_integer_only_bounded_json(kind: str) -> None:
    policy = PARTIAL_RETURN_TEMPLATE_JSON_POLICY
    if kind == "duplicate":
        encoded = '{"x":1,"x":2}'
    elif kind == "nonfinite":
        encoded = '{"x":Infinity}'
    elif kind == "fraction":
        encoded = '{"x":1e0}'
    else:
        graph: Any = 0
        if kind == "depth":
            for _ in range(policy.max_depth + 1):
                graph = [graph]
        elif kind == "collection":
            graph = [0] * (policy.max_collection_items + 1)
        elif kind == "nodes":
            graph = [[0] * policy.max_collection_items
                     for _ in range(policy.max_nodes // policy.max_collection_items)]
        elif kind == "scalar":
            graph = "x" * (policy.max_scalar_characters + 1)
        else:
            graph = "x" * policy.max_file_bytes
        encoded = json.dumps({"graph": graph}, separators=(",", ":"))
        assert (len(encoded.encode("utf8")) > policy.max_file_bytes) == (kind == "bytes")
    with pytest.raises(FinancePostingError) as refused:
        PartialReturnCorrectionTemplate(encoded)
    assert refused.value.code == "customer_partial_return_posting_invalid"
    if kind != "bytes":
        assert isinstance(refused.value.__context__, StructuredDocumentError)
