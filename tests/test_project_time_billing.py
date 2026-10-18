"""Executable minute-price allocation before the native PB1 owner is installed."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict
from decimal import Inexact, Rounded, localcontext
from itertools import permutations
from pathlib import Path

import pytest

from reconforge.domain.finance_policy import FinanceCurrencyPolicy
from reconforge.domain.finance_posting import FinancePostingError, digest_payload
from reconforge.domain.people_project_payroll import PeopleScope
from reconforge.domain.project_time_billing import ProjectPriceAgreement, allocate_bill, collection_amount
from reconforge.utils.money import CurrencyRegistry, CurrencyRegistryContext
from tests.verify_project_time_billing_oracle import verify as independently_verify

SCOPE = PeopleScope("work", "org", "entity", "ORG", "ENTITY")
CONTEXT = CurrencyRegistry.context()
POLICY = {"currency_code": "USD", **FinanceCurrencyPolicy.capture("USD", CONTEXT).metadata()}


def inputs():
    scope = {
        "tenant_id": "synthetic",
        **{name: getattr(SCOPE, name) for name in ("workspace_id", "organization_id", "legal_entity_id")},
    }
    prices = []
    for index, rate in ((1, 2000), (2, 1500)):
        source = {
            **scope,
            "id": f"PRICE-{index}",
            "project_id": f"PROJECT-{index}",
            "customer_code": "CUSTOMER",
            "currency_code": "USD",
            "valid_from": "2026-10-01",
            "valid_through": "2026-10-31",
            "hourly_price_minor": rate,
            "preparer_id": "maker",
            "dimension_id": "PROJECT",
            "value_id": f"P{index}",
            "monetary_policy": POLICY,
        }
        prices.append(
            {**source, "source_json": source, "source_digest": digest_payload(source), "approver_id": "checker"}
        )
    times = []
    for index, (first, end) in enumerate(((61, 90), (15, 60)), 1):
        request = {
            "employee_id": f"EMP-{index}",
            "business_date": "2026-10-03",
            "lines": [
                {"project_id": "PROJECT-1", "start_minute": 0, "end_minute": first},
                {"project_id": "PROJECT-2", "start_minute": first, "end_minute": end},
            ],
            "reason": "Synthetic approved service time",
        }
        times.append(
            {
                **scope,
                **request,
                "id": f"TIME-{index}",
                "request_json": request,
                "employment_id": f"VERSION-{index}",
                "source_digest": digest_payload({**request, "employment_id": f"VERSION-{index}"}),
                "submitter_id": "maker",
                "approver_id": "checker",
            }
        )
    return times, prices


def calculate(times=None, prices=None):
    original_times, original_prices = inputs()
    return allocate_bill(
        SCOPE,
        tenant_id="synthetic",
        customer_code="CUSTOMER",
        currency_code="USD",
        registry_context=CONTEXT,
        approved_time=original_times if times is None else times,
        approved_prices=original_prices if prices is None else prices,
    )


def test_exact_approved_time_project_revenue_and_native_ar_line_conservation():
    result = calculate()
    assert result["project_minutes"] == {"PROJECT-1": 76, "PROJECT-2": 74}
    assert result["project_minor"] == {"PROJECT-1": 2533, "PROJECT-2": 1850}
    assert result["amount_minor"] == 4383
    assert all(
        row["quantity"] == "1" and row["unit_price_minor"] == row["line_total_minor"] and row["tax_minor"] == 0
        for row in result["ar_lines"]
    )
    assert len(result["sources"]) == 4 and result["time_ids"] == ["TIME-1", "TIME-2"]


def test_reordering_whole_time_and_price_sources_is_deterministic():
    times, prices = inputs()
    expected = calculate()
    for sources in permutations(times):
        for agreements in permutations(prices):
            assert calculate(sources, agreements) == expected


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_time",
        "foreign_time",
        "unapproved_time",
        "own_approval",
        "digest",
        "minutes_bool",
        "minutes_float",
        "overlap",
        "missing_price",
        "price_overlap",
        "own_price_approval",
        "price_digest",
        "price_currency",
        "price_customer",
        "price_scope",
        "unused_price",
    ],
)
def test_source_admission_refuses_duplicate_unapproved_ambiguous_or_foreign_input(mutation):
    times, prices = copy.deepcopy(inputs())
    if mutation == "duplicate_time":
        times.append(copy.deepcopy(times[0]))
    elif mutation == "foreign_time":
        times[0]["workspace_id"] = "foreign"
    elif mutation == "unapproved_time":
        times[0]["approver_id"] = None
    elif mutation == "own_approval":
        times[0]["approver_id"] = "maker"
    elif mutation == "digest":
        times[0]["source_digest"] = "0" * 64
    elif mutation == "minutes_bool":
        times[0]["lines"][0]["start_minute"] = False
    elif mutation == "minutes_float":
        times[0]["lines"][0]["start_minute"] = 0.0
    elif mutation == "overlap":
        times[0]["lines"][1]["start_minute"] = 0
    elif mutation == "missing_price":
        prices.pop()
    elif mutation == "price_overlap":
        prices.append(copy.deepcopy(prices[0]))
        prices[-1]["id"] = "PRICE-other"
        prices[-1]["source_json"]["id"] = "PRICE-other"
        prices[-1]["source_digest"] = digest_payload(prices[-1]["source_json"])
    elif mutation == "own_price_approval":
        prices[0]["approver_id"] = "maker"
    elif mutation == "price_digest":
        prices[0]["source_digest"] = "0" * 64
    elif mutation == "price_currency":
        prices[0]["currency_code"] = "EUR"
    elif mutation == "price_customer":
        prices[0]["customer_code"] = "FOREIGN"
    elif mutation == "price_scope":
        prices[0]["legal_entity_id"] = "foreign"
    elif mutation == "unused_price":
        prices.append(copy.deepcopy(prices[0]))
        prices[-1]["id"] = "PRICE-unused"
        prices[-1]["project_id"] = "PROJECT-unused"
        prices[-1]["source_json"].update(id="PRICE-unused", project_id="PROJECT-unused")
        prices[-1]["source_digest"] = digest_payload(prices[-1]["source_json"])
    if mutation in {"minutes_bool", "minutes_float", "overlap"}:
        times[0]["source_digest"] = digest_payload(
            {**times[0]["request_json"], "employment_id": times[0]["employment_id"]}
        )
    with pytest.raises(FinancePostingError):
        calculate(times, prices)


@pytest.mark.parametrize("value", [True, 1.0, "1", 0, -1, 4_500_000_000_000_000_001])
def test_price_request_uses_explicit_native_bounded_minor_units(value):
    with pytest.raises(FinancePostingError):
        ProjectPriceAgreement(
            SCOPE, "CUSTOMER", "PROJECT-1", "2026-10-01", "2026-10-31", "USD", value, "Synthetic price"
        )


def test_request_payload_reuses_original_scope_without_personnel_pay_rates():
    request = ProjectPriceAgreement(
        SCOPE, "CUSTOMER", "PROJECT-1", "2026-10-01", "2026-10-31", "USD", 2000, "Synthetic price"
    )
    assert request.payload() == {
        **{key: value for key, value in asdict(request).items() if key != "scope"},
        **asdict(SCOPE),
    }
    assert "hourly_rate_minor" not in request.payload()


def test_exact_partial_final_collections_preserve_original_receivable():
    first = collection_amount(4383, 0, 1000)
    assert first == {"amount_minor": 1000, "collected_after_minor": 1000, "outstanding_after_minor": 3383}
    assert collection_amount(4383, 1000, 3383)["outstanding_after_minor"] == 0
    with pytest.raises(FinancePostingError, match="exceeds"):
        collection_amount(4383, 1000, 3384)


@pytest.mark.parametrize("precision", [0, 2, 3, 8])
def test_half_tie_reuses_captured_money_half_up_at_all_currency_scales(precision):
    context = CurrencyRegistryContext.from_snapshot(
        {
            "schema_version": 1,
            "registry_version": "synthetic-price-v1",
            "source": "Synthetic currency test",
            "source_url": "",
            "published_at": "",
            "currencies": [
                {
                    "code": "TST",
                    "name": "Synthetic precision",
                    "minor_units": precision,
                    "rounding_policy": "ROUND_HALF_UP",
                }
            ],
        }
    )
    policy = {"currency_code": "TST", **FinanceCurrencyPolicy.capture("TST", context).metadata()}
    times, prices = inputs()
    times = times[:1]
    times[0]["lines"] = [{"project_id": "PROJECT-1", "start_minute": 0, "end_minute": 30}]
    times[0]["request_json"]["lines"] = times[0]["lines"]
    times[0]["source_digest"] = digest_payload({**times[0]["request_json"], "employment_id": times[0]["employment_id"]})
    prices = prices[:1]
    prices[0].update(currency_code="TST", hourly_price_minor=5, monetary_policy=policy)
    prices[0]["source_json"].update(currency_code="TST", hourly_price_minor=5, monetary_policy=policy)
    prices[0]["source_digest"] = digest_payload(prices[0]["source_json"])
    calculation = allocate_bill(
        SCOPE,
        tenant_id="synthetic",
        customer_code="CUSTOMER",
        currency_code="TST",
        registry_context=context,
        approved_time=times,
        approved_prices=prices,
    )
    assert calculation["amount_minor"] == 3
    proof = {
        "schema_version": "project-billing-allocation-evidence-v1",
        "scope": {
            "tenant_id": "synthetic",
            **{name: getattr(SCOPE, name) for name in ("workspace_id", "organization_id", "legal_entity_id")},
        },
        "customer_code": "CUSTOMER",
        "currency_code": "TST",
        "registry_snapshot": context.snapshot(),
        "times": times,
        "prices": prices,
        "calculation": calculation,
    }
    assert independently_verify(proof)["amount_minor"] == 3


def test_captured_price_policy_drift_refused_before_native_ar_planning():
    times, prices = inputs()
    prices[0]["monetary_policy"] = {**POLICY, "currency_rounding_policy": "ROUND_HALF_EVEN"}
    with pytest.raises(FinancePostingError, match="captured native monetary policy"):
        calculate(times, prices)


def test_large_exact_fraction_numerator_and_hostile_decimal_context_reuse_native_money():
    times, prices = inputs()
    times = times[:1]
    times[0]["lines"] = [{"project_id": "PROJECT-1", "start_minute": 0, "end_minute": 61}]
    times[0]["request_json"]["lines"] = times[0]["lines"]
    times[0]["source_digest"] = digest_payload({**times[0]["request_json"], "employment_id": times[0]["employment_id"]})
    prices = prices[:1]
    prices[0]["hourly_price_minor"] = 4_400_000_000_000_000_000
    prices[0]["source_json"]["hourly_price_minor"] = prices[0]["hourly_price_minor"]
    prices[0]["source_digest"] = digest_payload(prices[0]["source_json"])
    with localcontext() as hostile:
        hostile.prec = 2
        hostile.traps[Inexact] = True
        hostile.traps[Rounded] = True
        result = calculate(times, prices)
    assert result["amount_minor"] == 4_473_333_333_333_333_333
    proof = evidence()
    proof.update(times=times, prices=prices, calculation=result)
    assert independently_verify(proof)["amount_minor"] == result["amount_minor"]


def evidence():
    times, prices = inputs()
    return {
        "schema_version": "project-billing-allocation-evidence-v1",
        "scope": {
            "tenant_id": "synthetic",
            **{name: getattr(SCOPE, name) for name in ("workspace_id", "organization_id", "legal_entity_id")},
        },
        "customer_code": "CUSTOMER",
        "currency_code": "USD",
        "registry_snapshot": CONTEXT.snapshot(),
        "times": times,
        "prices": prices,
        "calculation": calculate(),
    }


def test_independent_fraction_oracle_proves_only_the_allocation():
    result = independently_verify(evidence())
    assert result["accepted_calculation"] is True and result["amount_minor"] == 4383
    assert result["native_ar_gl_proven"] is False and result["performance_comparison_accepted"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "amount",
        "balanced_projects",
        "native_ar_price",
        "price_seal",
        "time_seal",
        "time_scope",
        "customer",
        "claim_population",
        "actor",
        "unused_price",
    ],
)
def test_independent_oracle_refuses_changed_source_or_balanced_allocation(mutation):
    proof = copy.deepcopy(evidence())
    if mutation == "amount":
        proof["calculation"]["amount_minor"] += 1
    elif mutation == "balanced_projects":
        proof["calculation"]["project_minor"]["PROJECT-1"] += 1
        proof["calculation"]["project_minor"]["PROJECT-2"] -= 1
    elif mutation == "native_ar_price":
        proof["calculation"]["ar_lines"][0]["unit_price_minor"] += 1
    elif mutation == "price_seal":
        proof["prices"][0]["source_digest"] = "0" * 64
    elif mutation == "time_seal":
        proof["times"][0]["source_digest"] = "0" * 64
    elif mutation == "time_scope":
        proof["times"][0]["workspace_id"] = "foreign"
    elif mutation == "customer":
        proof["customer_code"] = "FOREIGN"
    elif mutation == "claim_population":
        proof["calculation"]["time_ids"].pop()
    elif mutation == "actor":
        proof["prices"][0]["approver_id"] = "maker"
    elif mutation == "unused_price":
        proof["prices"].append(copy.deepcopy(proof["prices"][0]))
    with pytest.raises(ValueError):
        independently_verify(proof)


@pytest.mark.parametrize("optimized", [False, True])
def test_standalone_raw_anchored_allocation_normal_and_optimized(tmp_path: Path, optimized):
    original = tmp_path / "original.json"
    original.write_text(json.dumps(evidence(), sort_keys=True, separators=(",", ":")), encoding="utf-8")
    expected = hashlib.sha256(original.read_bytes()).hexdigest()
    output = tmp_path / "result.json"
    oracle = Path(__file__).with_name("verify_project_time_billing_oracle.py")
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            *(["-O"] if optimized else []),
            str(oracle),
            "--evidence",
            str(original),
            "--expected-evidence-sha256",
            expected,
            "--output",
            str(output),
        ],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    proof = json.loads(output.read_bytes())
    assert (
        proof["raw_export_anchor"] is True and proof["native_ar_gl_proven"] is False and proof["amount_minor"] == 4383
    )
    original.write_bytes(original.read_bytes() + b" ")
    changed = tmp_path / "changed.json"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            *(["-O"] if optimized else []),
            str(oracle),
            "--evidence",
            str(original),
            "--expected-evidence-sha256",
            expected,
            "--output",
            str(changed),
        ],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0 and not changed.exists()
