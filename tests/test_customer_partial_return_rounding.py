"""Literal residual-rounding vectors and hostile immutable-prefix controls."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from reconforge.domain.customer_partial_return_rounding import (
    RemainingReturnHistory,
    apply_remaining_return,
    prepare_remaining_return,
    remaining_return_balance,
    reverse_remaining_return,
    verify_remaining_return_plan,
)
from reconforge.domain.customer_partial_return_rounding_posting import build_remaining_posting_contract
from reconforge.domain.customer_partial_returns import PartialReturnHistory, prepare_partial_return
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.inventory_costing import allocate_fifo_value
from tests.test_customer_partial_return_design import DESIGN
from tests.test_customer_partial_return_posting import INTENT, roles_for
from tests.test_customer_partial_returns_domain import source_for


def original(quantity: int = 3, cost: int = 1001, unit: int = 1000) -> Any:
    case = deepcopy(DESIGN['cases'][0])
    case.update(quantity_precision=0, quantity_scaled=quantity, gross_minor=quantity*unit,
                net_unit_price_minor=unit, collected_minor=0)
    case['consumptions'] = [{'id':'ORIGINAL-CONSUMPTION','layer_id':'ORIGINAL-LAYER',
                             'quantity_scaled':quantity,'value_minor':cost}]
    return source_for(case)


@pytest.mark.parametrize(('cuts','expected'), [([1,1,1],[334,334,333]),([2,1],[667,334])])
def test_original_remaining_cost_is_path_sensitive_and_conserves_final_minor(cuts: list[int], expected: list[int]) -> None:
    source = original()
    oldfp = source.fingerprint
    history = RemainingReturnHistory(source)
    actual = []
    for quantity in cuts:
        plan = prepare_remaining_return(history,quantity)
        actual.append(plan.cogs_restored_minor)
        assert plan.portions[0].before_value_minor == 1001-sum(actual[:-1])
        history = apply_remaining_return(history,plan)
    balance = remaining_return_balance(history)
    assert actual == expected and balance.cogs_restored_minor == 1001 and balance.credited_minor == 3000
    assert source.fingerprint == oldfp
    with pytest.raises(FinancePostingError,match='integral'):
        prepare_partial_return(PartialReturnHistory(source),1)


def test_reversal_reinstates_exact_before_value_then_different_split_is_recomputed() -> None:
    history = RemainingReturnHistory(original())
    first = prepare_remaining_return(history,1)
    history = apply_remaining_return(history,first)
    history = reverse_remaining_return(history,1)
    assert history.events[-1].return_values == history.events[0].return_values
    assert remaining_return_balance(history).cogs_restored_minor == 0
    next_plan = prepare_remaining_return(history,2)
    assert next_plan.cogs_restored_minor == 667
    assert next_plan.portions[0].before_value_minor == 1001


@pytest.mark.parametrize(('quantity','cost','unit','expected_purposes'), [
    (3,1,1,['RevenueCredit']), (3,1001,1,['RevenueCredit','CostRestoration']),
])
def test_zero_cost_omits_only_cost_journal_and_preserves_typed_physical_portion(
    quantity: int,cost: int,unit: int,expected_purposes: list[str],
) -> None:
    source = original(quantity,cost,unit)
    plan = prepare_remaining_return(RemainingReturnHistory(source),1)
    contract = build_remaining_posting_contract(plan,roles=roles_for(source),intent=INTENT).payload()
    assert [template['purpose'] for template in contract['templates']] == expected_purposes
    assert plan.quantity_scaled == 1 and len(plan.portions) == 1
    for template in contract['templates']:
        assert sum(line['debit_minor'] for line in template['lines']) == sum(line['credit_minor'] for line in template['lines']) > 0
        assert all((line['debit_minor'] > 0) != (line['credit_minor'] > 0) for line in template['lines'])


def test_zero_revenue_and_zero_cost_leg_have_no_finance_entry() -> None:
    # Captured original 3 scaled units at precision1, unit3 -> original gross1.
    case=deepcopy(DESIGN['cases'][0])
    case.update(quantity_precision=1,quantity_scaled=3,gross_minor=1,net_unit_price_minor=3,collected_minor=0)
    case['consumptions']=[{'id':'C','layer_id':'L','quantity_scaled':3,'value_minor':1}]
    source=source_for(case)
    history=RemainingReturnHistory(source)
    first=prepare_remaining_return(history,1)
    assert first.credit_minor == first.cogs_restored_minor == 0
    assert build_remaining_posting_contract(first,roles=roles_for(source),intent=INTENT).payload()['templates'] == []
    history=apply_remaining_return(history,first)
    second=prepare_remaining_return(history,1)
    assert second.credit_minor == 1 and second.cogs_restored_minor == 0  # HALF_UP vs HALF_EVEN
    history=apply_remaining_return(history,second)
    third=prepare_remaining_return(history,1)
    assert third.credit_minor == 0 and third.cogs_restored_minor == 1
    assert [x['purpose'] for x in build_remaining_posting_contract(third,roles=roles_for(source),intent=INTENT).payload()['templates']] == ['CostRestoration']
    history=apply_remaining_return(history,third)
    assert (remaining_return_balance(history).credited_minor,remaining_return_balance(history).cogs_restored_minor)==(1,1)


@pytest.mark.parametrize('field',['before_value_minor','before_quantity_scaled','value_minor','quantity_scaled'])
def test_balanced_or_unchanged_total_cannot_forge_the_retained_prefix_witness(field: str) -> None:
    history=RemainingReturnHistory(original())
    plan=prepare_remaining_return(history,1)
    part=replace(plan.portions[0],**{field:getattr(plan.portions[0],field)+1})
    with pytest.raises(FinancePostingError):
        verify_remaining_return_plan(replace(plan,portions=(part,)))


@pytest.mark.parametrize('mode',[None,0,1,'true',True])
def test_zero_mode_does_not_enter_default_or_accept_non_boolean(mode: Any) -> None:
    if mode is True:
        assert allocate_fifo_value(1,3,1,allow_zero=mode)==0
    else:
        with pytest.raises(ValueError):
            allocate_fifo_value(1,3,1,allow_zero=mode)
    with pytest.raises(ValueError):
        allocate_fifo_value(1,3,1)


@given(st.integers(1,50),st.integers(1,10000))
@settings(max_examples=45,deadline=None)
def test_existing_half_even_allocator_with_explicit_zero_mode_matches_fraction_ties(quantity: int,value: int) -> None:
    q,v=quantity,value
    total=0
    while q:
        expected=round(Fraction(v,q)) if q>1 else v
        actual=allocate_fifo_value(v,q,1,allow_zero=True)
        assert actual==expected and 0<=actual<=v
        total+=actual
        v-=actual
        q-=1
    assert total==value and v==0


@pytest.mark.parametrize('bad',[True,1.0,'1',0,-1,None])
def test_untrusted_quantity_refuses_before_money_math(bad: Any) -> None:
    with pytest.raises(FinancePostingError):
        prepare_remaining_return(RemainingReturnHistory(original()),bad)


@pytest.mark.parametrize(('selected','expected'),[(4499999999999499999,4499999999999),(8999999999999999999,9000000000000)])
def test_large_exact_ratios_do_not_preround_the_half_or_exceed_the_original(selected: int,expected: int) -> None:
    case=deepcopy(DESIGN['cases'][0])
    case.update(quantity_precision=6,quantity_scaled=9000000000000000000,gross_minor=9000000000000,
                net_unit_price_minor=1,collected_minor=0)
    case['consumptions']=[{'id':'LARGE-C','layer_id':'LARGE-L','quantity_scaled':9000000000000000000,'value_minor':9000000000000}]
    source=source_for(case)
    plan=prepare_remaining_return(RemainingReturnHistory(source),selected)
    assert plan.credit_minor == plan.cogs_restored_minor == expected
