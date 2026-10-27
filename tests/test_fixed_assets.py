"""Independent exact entitlements and acquisition/disposal accounting oracles."""

from decimal import ROUND_HALF_UP, Decimal, localcontext

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.fixed_assets import (
    AssetRegister,
    AssetRegisterState,
    MultiRegisterAssetAcquisition,
    accounting_lines,
    cumulative_depreciation,
    cumulative_post_impairment_depreciation,
    eligible_months,
    impairment_lines,
    multi_register_disposal_lines,
    recalibrate_post_impairment_depreciation,
)


@pytest.mark.parametrize("cost,salvage,life", [(10000, 1000, 3), (101, 0, 7), (9007199254740993, 999, 1200)])
def test_cumulative_entitlement_matches_independent_decimal_oracle(cost: int, salvage: int, life: int) -> None:
    previous = 0
    with localcontext() as context:
        context.prec = 60
        for month in range(life + 1):
            oracle = int((Decimal(cost - salvage) * Decimal(month) / Decimal(life)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
            actual = cumulative_depreciation(cost, salvage, life, month)
            assert actual == oracle
            assert actual >= previous
            previous = actual
    assert previous == cost - salvage


@pytest.mark.parametrize("cost,salvage,life,months", [(100, 100, 3, 0), (100, -1, 3, 0), (True, 0, 3, 0), (100, 0, 0, 0), (100, 0, 3, 4), (100, 0, 3, True)])
def test_invalid_exact_bases_are_refused(cost: int, salvage: int, life: int, months: int) -> None:
    with pytest.raises(FinancePostingError):
        cumulative_depreciation(cost, salvage, life, months)


@pytest.mark.parametrize("proceeds", [0, 4000, 7000, 9000])
def test_disposal_equation_releases_historical_cost_and_accumulation(proceeds: int) -> None:
    asset = {"cost_minor": 10000, "salvage_minor": 1000, **{key + "_account_code": key.upper()
             for key in ("asset", "accumulated", "expense", "cash", "gain", "loss")}}
    lines = accounting_lines(asset, "dispose", accumulated=3000, proceeds=proceeds)
    by_account = {row["account_code"]: int(row["debit_minor"]) - int(row["credit_minor"]) for row in lines}
    assert sum(by_account.values()) == 0
    assert by_account["ASSET"] == -10000
    assert by_account["ACCUMULATED"] == 3000
    assert by_account.get("CASH", 0) == proceeds
    assert by_account.get("LOSS", 0) == max(7000 - proceeds, 0)
    assert by_account.get("GAIN", 0) == -max(proceeds - 7000, 0)


def test_completed_service_months_and_catchup_are_exact() -> None:
    assert eligible_months("2026-01-15", "2026-01", "2026-02-01", 36) == 1
    assert eligible_months("2026-01-15", "2026-09", "2026-10-01", 36) == 9
    assert eligible_months("2026-01-15", "2029-01", "2029-02-01", 36) == 36
    for month, posted in (("2026-01", "2026-01-31"), ("2025-12", "2026-02-01"), ("2026-13", "2027-02-01")):
        with pytest.raises(FinancePostingError):
            eligible_months("2026-01-15", month, posted, 36)


def test_impairment_accounting_recognizes_loss_and_updates_accumulated() -> None:
    asset = {"cost_minor": 10000, "salvage_minor": 1000, **{key + "_account_code": key.upper()
             for key in ("asset", "accumulated", "expense", "cash", "gain", "loss")}}
    lines = accounting_lines(asset, "impair", accumulated=3000, impairment=2500)
    by_account = {row["account_code"]: int(row["debit_minor"]) - int(row["credit_minor"]) for row in lines}
    assert sum(by_account.values()) == 0
    assert by_account["LOSS"] == 2500
    assert by_account["ACCUMULATED"] == -2500


def test_impairment_exceeding_carrying_basis_is_refused() -> None:
    asset = {"cost_minor": 10000, "salvage_minor": 1000, **{key + "_account_code": key.upper()
             for key in ("asset", "accumulated", "expense", "cash", "gain", "loss")}}
    # Maximum depreciable basis is 10000 - 1000 = 9000. Accumulated is 8000, so max impairment is 1000.
    with pytest.raises(FinancePostingError):
        accounting_lines(asset, "impair", accumulated=8000, impairment=1001)


def _sample_register(
    code: str = "STATUTORY",
    cost: int = 120000,
    salvage: int = 12000,
    life: int = 60,
) -> AssetRegister:
    return AssetRegister(
        register_code=code,
        cost_minor=cost,
        salvage_minor=salvage,
        useful_life_months=life,
        asset_account_code=f"{code}_ASSET",
        accumulated_depreciation_account_code=f"{code}_ACC_DEP",
        accumulated_impairment_account_code=f"{code}_ACC_IMP",
        depreciation_expense_account_code=f"{code}_DEP_EXP",
        impairment_loss_account_code=f"{code}_IMP_LOSS",
        gain_account_code=f"{code}_GAIN",
        loss_account_code=f"{code}_LOSS",
    )


def test_multi_register_asset_acquisition_and_lines() -> None:
    reg_stat = _sample_register("STATUTORY", cost=100000, salvage=10000, life=60)
    reg_tax = _sample_register("TAX", cost=100000, salvage=0, life=40)
    reg_ifrs = _sample_register("IFRS", cost=100000, salvage=10000, life=60)

    acq = MultiRegisterAssetAcquisition(
        workspace_id="WS01",
        organization_id="ORG01",
        legal_entity_id="LE01",
        organization_code="CORP",
        entity_code="ENT1",
        asset_number="FA-2026-001",
        name="Industrial CNC Machine",
        journal_code="FA-JOURNAL",
        period_id="2026-10",
        posting_date="2026-10-01",
        in_service_date="2026-10-05",
        registers=(reg_stat, reg_tax, reg_ifrs),
        cash_account_code="CASH_CLEARING",
    )
    lines = acq.acquisition_lines()
    assert len(lines) == 2
    assert lines[0] == {"account_code": "STATUTORY_ASSET", "debit_minor": 100000, "credit_minor": 0}
    assert lines[1] == {"account_code": "CASH_CLEARING", "debit_minor": 0, "credit_minor": 100000}
    assert sum(line["debit_minor"] for line in lines) == sum(line["credit_minor"] for line in lines)

    # In service before posting is refused
    with pytest.raises(FinancePostingError, match="Service date cannot precede acquisition"):
        MultiRegisterAssetAcquisition(
            workspace_id="WS01", organization_id="ORG01", legal_entity_id="LE01",
            organization_code="CORP", entity_code="ENT1", asset_number="FA-002",
            name="Machine", journal_code="FA", period_id="2026-10",
            posting_date="2026-10-15", in_service_date="2026-10-01",
            registers=(reg_stat,), cash_account_code="CASH",
        )

    # Duplicate register codes refused
    with pytest.raises(FinancePostingError, match="distinct"):
        MultiRegisterAssetAcquisition(
            workspace_id="WS01", organization_id="ORG01", legal_entity_id="LE01",
            organization_code="CORP", entity_code="ENT1", asset_number="FA-003",
            name="Machine", journal_code="FA", period_id="2026-10",
            posting_date="2026-10-01", in_service_date="2026-10-01",
            registers=(reg_stat, reg_stat), cash_account_code="CASH",
        )


def test_asset_register_state_lifecycle_and_invariants() -> None:
    reg = _sample_register("STATUTORY", cost=100000, salvage=10000, life=60)
    state = AssetRegisterState.create(reg, accumulated_depreciation_minor=20000, accumulated_impairment_minor=5000, months_depreciated=12)
    assert state.carrying_value_minor == 75000
    assert state.months_depreciated == 12

    # Depreciate further
    state2 = state.with_depreciation(1500, months=1)
    assert state2.accumulated_depreciation_minor == 21500
    assert state2.carrying_value_minor == 73500
    assert state2.months_depreciated == 13

    # Impair
    state3 = state2.with_impairment(13500)
    assert state3.accumulated_impairment_minor == 18500
    assert state3.carrying_value_minor == 60000

    # Over-impairment refused
    with pytest.raises(FinancePostingError, match="exceeds carrying value"):
        state3.with_impairment(60001)

    # Over-depreciation refused
    with pytest.raises(FinancePostingError, match="exceeds carrying value"):
        state3.with_depreciation(60001)


def test_impairment_lines_generation_and_balance() -> None:
    reg = _sample_register("STATUTORY", cost=100000, salvage=10000, life=50)
    state = AssetRegisterState.create(reg, accumulated_depreciation_minor=30000, months_depreciated=15)
    assert state.carrying_value_minor == 70000

    # Recoverable amount is 50,000 -> loss of 20,000
    loss, lines = impairment_lines(reg, state, recoverable_amount_minor=50000)
    assert loss == 20000
    assert len(lines) == 2
    assert lines[0] == {"account_code": "STATUTORY_IMP_LOSS", "debit_minor": 20000, "credit_minor": 0}
    assert lines[1] == {"account_code": "STATUTORY_ACC_IMP", "debit_minor": 0, "credit_minor": 20000}
    assert sum(line["debit_minor"] for line in lines) == sum(line["credit_minor"] for line in lines)

    # Recoverable amount >= carrying -> no impairment
    no_loss, no_lines = impairment_lines(reg, state, recoverable_amount_minor=75000)
    assert no_loss == 0
    assert no_lines == []


def test_post_impairment_depreciation_recalibration() -> None:
    # Asset cost 100,000, salvage 10,000, life 100 months. Monthly depr = (100000 - 10000)/100 = 900.
    reg = _sample_register("STATUTORY", cost=100000, salvage=10000, life=100)
    # After 20 months: depr = 18,000. Carrying = 82,000.
    state = AssetRegisterState.create(reg, accumulated_depreciation_minor=18000, months_depreciated=20)
    assert state.carrying_value_minor == 82000

    # Impairment to recoverable amount 55,000 -> loss 27,000.
    loss, imp_lines = impairment_lines(reg, state, recoverable_amount_minor=55000)
    assert loss == 27000
    post_state = state.with_impairment(loss)
    assert post_state.carrying_value_minor == 55000

    # Remaining life = 80 months, remaining depreciable basis = 55,000 - 10,000 = 45,000.
    # Monthly rate = 45,000 / 80 = 562.5.
    prev = 0
    for elapsed in range(1, 81):
        cum = recalibrate_post_impairment_depreciation(reg, post_state, elapsed)
        # Decimal half-up oracle check:
        oracle = int((Decimal(45000) * Decimal(elapsed) / Decimal(80)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        assert cum == oracle
        assert cum >= prev
        prev = cum
    # At end of life, exactly 45,000 depreciated!
    assert prev == 45000
    final_carrying = post_state.carrying_value_minor - prev
    assert final_carrying == reg.salvage_minor == 10000


def test_multi_register_disposal_lines_gain_and_loss_balance() -> None:
    reg_stat = _sample_register("STATUTORY", cost=100000, salvage=10000, life=60)
    reg_tax = _sample_register("TAX", cost=100000, salvage=0, life=40)
    reg_ifrs = _sample_register("IFRS", cost=100000, salvage=10000, life=60)

    acq = MultiRegisterAssetAcquisition(
        workspace_id="WS01", organization_id="ORG01", legal_entity_id="LE01",
        organization_code="CORP", entity_code="ENT1", asset_number="FA-001",
        name="Asset", journal_code="FA", period_id="2026-10",
        posting_date="2026-10-01", in_service_date="2026-10-01",
        registers=(reg_stat, reg_tax, reg_ifrs), cash_account_code="CASH",
    )

    # State:
    # Statutory: cost 100k, accum_dep 30k, accum_imp 10k -> carrying 60k.
    # Tax: cost 100k, accum_dep 60k, accum_imp 0 -> carrying 40k.
    # IFRS: cost 100k, accum_dep 25k, accum_imp 5k -> carrying 70k.
    states = {
        "STATUTORY": AssetRegisterState.create(reg_stat, accumulated_depreciation_minor=30000, accumulated_impairment_minor=10000, months_depreciated=18),
        "TAX": AssetRegisterState.create(reg_tax, accumulated_depreciation_minor=60000, accumulated_impairment_minor=0, months_depreciated=24),
        "IFRS": AssetRegisterState.create(reg_ifrs, accumulated_depreciation_minor=25000, accumulated_impairment_minor=5000, months_depreciated=15),
    }

    # Proceeds = 70,000
    # Statutory: carrying 60k, proceeds 70k -> Gain of 10,000.
    # Tax: carrying 40k, proceeds 70k -> Gain of 30,000.
    # IFRS: carrying 70k, proceeds 70k -> Gain 0, Loss 0.
    disposal_lines = multi_register_disposal_lines(acq, states, proceeds_minor=70000, proceeds_cash_account="BANK_CASH")
    assert set(disposal_lines.keys()) == {"STATUTORY", "TAX", "IFRS"}

    for code, lines in disposal_lines.items():
        debit = sum(line["debit_minor"] for line in lines)
        credit = sum(line["credit_minor"] for line in lines)
        assert debit == credit, f"Register {code} lines out of balance: {debit} != {credit}"

    stat_by_account = {line["account_code"]: line["debit_minor"] - line["credit_minor"] for line in disposal_lines["STATUTORY"]}
    assert stat_by_account["BANK_CASH"] == 70000
    assert stat_by_account["STATUTORY_ACC_DEP"] == 30000
    assert stat_by_account["STATUTORY_ACC_IMP"] == 10000
    assert stat_by_account["STATUTORY_ASSET"] == -100000
    assert stat_by_account["STATUTORY_GAIN"] == -10000

    # Now test with lower proceeds (loss case):
    # Proceeds = 30,000
    # Statutory: carrying 60k, proceeds 30k -> Loss of 30,000.
    # Tax: carrying 40k, proceeds 30k -> Loss of 10,000.
    # IFRS: carrying 70k, proceeds 30k -> Loss of 40,000.
    loss_lines = multi_register_disposal_lines(acq, states, proceeds_minor=30000, proceeds_cash_account="BANK_CASH")
    for code, lines in loss_lines.items():
        debit = sum(line["debit_minor"] for line in lines)
        credit = sum(line["credit_minor"] for line in lines)
        assert debit == credit, f"Register {code} loss lines out of balance: {debit} != {credit}"

    stat_loss_by_account = {line["account_code"]: line["debit_minor"] - line["credit_minor"] for line in loss_lines["STATUTORY"]}
    assert stat_loss_by_account["BANK_CASH"] == 30000
    assert stat_loss_by_account["STATUTORY_ACC_DEP"] == 30000
    assert stat_loss_by_account["STATUTORY_ACC_IMP"] == 10000
    assert stat_loss_by_account["STATUTORY_LOSS"] == 30000
    assert stat_loss_by_account["STATUTORY_ASSET"] == -100000

    # Also directly test cumulative_post_impairment_depreciation helper
    assert cumulative_post_impairment_depreciation(45000, 80, 0) == 0
    assert cumulative_post_impairment_depreciation(45000, 80, 80) == 45000
    assert cumulative_post_impairment_depreciation(45000, 0, 0) == 0

