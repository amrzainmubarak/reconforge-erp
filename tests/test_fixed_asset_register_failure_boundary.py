"""Register persistence failures must remain visible before financial preparation."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.fixed_assets import AssetRegister, MultiRegisterAssetAcquisition
from reconforge.infrastructure import postgres_fixed_assets as module


def acquisition() -> MultiRegisterAssetAcquisition:
    register = AssetRegister(
        register_code="STATUTORY", cost_minor=10_000, salvage_minor=0, useful_life_months=12,
        asset_account_code="FIXED", accumulated_depreciation_account_code="ACCUM",
        accumulated_impairment_account_code="ACCUM", depreciation_expense_account_code="EXPENSE",
        impairment_loss_account_code="LOSS", gain_account_code="GAIN", loss_account_code="LOSS",
    )
    return MultiRegisterAssetAcquisition(
        workspace_id="work", organization_id="org", legal_entity_id="entity",
        organization_code="ORG", entity_code="ENTITY", asset_number="SYNTHETIC-1", name="Synthetic asset",
        journal_code="STOCK", period_id="period", posting_date="2026-10-01", in_service_date="2026-10-01",
        registers=(register,), cash_account_code="CASH",
    )


def repository(monkeypatch: pytest.MonkeyPatch, *, fail_register_write: bool) -> tuple[Any, list[str], Mock]:
    statements: list[str] = []

    class Connection:
        def execute(self, query: str, parameters: object = None) -> None:
            statements.append(query)
            if fail_register_write and "INSERT INTO reconforge.fixed_asset_register_states" in query:
                raise RuntimeError("synthetic register persistence refusal")

    repo = module.PostgresFixedAssetsRepository.__new__(module.PostgresFixedAssetsRepository)
    repo.connection, repo.tenant_id = Connection(), "tenant-a"
    repo.owner = SimpleNamespace(_transaction=nullcontext, _actor=Mock())
    repo._command = Mock(return_value=("synthetic-digest", None))
    prepared = Mock(return_value={"unexpected_financial_preparation": True})
    repo._prepare = prepared
    monkeypatch.setattr(module, "records", lambda result: [{"currency_code": "USD", "currency_precision": 2}])
    return repo, statements, prepared


def test_unversioned_register_owner_is_refused_before_financial_preparation(monkeypatch: pytest.MonkeyPatch) -> None:
    repo, statements, prepared = repository(monkeypatch, fail_register_write=True)
    actor = PostingActor("maker", "maker", frozenset({"finance_core.manage"}))
    with pytest.raises(FinancePostingError) as failure:
        repo.acquire_multi_register(acquisition(), command_id="synthetic-command", actor=actor)
    assert failure.value.code == "asset_multi_register_owner_required"
    assert statements == []
    prepared.assert_not_called()


def test_acquisition_never_creates_schema_at_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    repo, statements, _prepared = repository(monkeypatch, fail_register_write=False)
    actor = PostingActor("maker", "maker", frozenset({"finance_core.manage"}))
    with pytest.raises(FinancePostingError) as failure:
        repo.acquire_multi_register(acquisition(), command_id="synthetic-command", actor=actor)
    assert failure.value.code == "asset_multi_register_owner_required"
    assert statements == []
    assert not any(token in query.upper() for query in statements for token in ("CREATE TABLE", "ALTER TABLE", "CREATE POLICY", "DROP POLICY"))
