"""Unsupported register requests cannot create unpublishable native financial state."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.fixed_assets import AssetRegister, MultiRegisterAssetAcquisition
from reconforge.infrastructure.postgres_fixed_assets import PostgresFixedAssetsRepository


def _request() -> MultiRegisterAssetAcquisition:
    register = AssetRegister(
        register_code="STATUTORY", cost_minor=10001, salvage_minor=1, useful_life_months=12,
        asset_account_code="ASSET", accumulated_depreciation_account_code="DEPRECIATION",
        accumulated_impairment_account_code="IMPAIRMENT", depreciation_expense_account_code="EXPENSE",
        impairment_loss_account_code="LOSS", gain_account_code="GAIN", loss_account_code="LOSS",
    )
    return MultiRegisterAssetAcquisition(
        workspace_id="work", organization_id="org", legal_entity_id="entity",
        organization_code="ORG", entity_code="ENTITY", asset_number="SYNTHETIC-1", name="Synthetic asset",
        journal_code="ASSET", period_id="period", posting_date="2026-10-01", in_service_date="2026-10-01",
        registers=(register, replace(register, register_code="TAX", cost_minor=9001)),
        cash_account_code="CASH",
    )


@pytest.mark.parametrize("mutation", ["unchanged", "cost", "life", "account", "primary_impairment", "remove_register"])
def test_unsupported_register_request_fails_before_any_financial_io(mutation: str) -> None:
    repository = PostgresFixedAssetsRepository.__new__(PostgresFixedAssetsRepository)
    repository.connection = Mock()
    repository.owner = SimpleNamespace(_transaction=Mock())
    repository._prepare = Mock()
    original = _request()
    actor = PostingActor("maker", "maker", frozenset({"finance_core.manage"}))
    primary, secondary = original.registers
    if mutation == "cost":
        secondary = replace(secondary, cost_minor=9002)
    elif mutation == "life":
        secondary = replace(secondary, useful_life_months=13)
    elif mutation == "account":
        secondary = replace(secondary, depreciation_expense_account_code="OTHER_EXPENSE")
    elif mutation == "primary_impairment":
        primary = replace(primary, impairment_loss_account_code="OTHER_LOSS")
    registers = (primary,) if mutation == "remove_register" else (primary, secondary)
    changed = replace(original, registers=registers)
    with pytest.raises(FinancePostingError) as failure:
        repository.acquire_multi_register(changed, command_id="same-command", actor=actor)
    assert failure.value.code == "asset_multi_register_owner_required"
    repository.owner._transaction.assert_not_called()
    repository.connection.execute.assert_not_called()
    repository._prepare.assert_not_called()
