"""Unsupported native multi-register refusal and supported single-register control."""
from dataclasses import replace

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.fixed_assets import AssetRegister, MultiRegisterAssetAcquisition
from reconforge.infrastructure.postgres_fixed_assets import PostgresFixedAssetsRepository
from tests.test_postgres_fixed_assets import acquire, asset_runtime, balances, finish, operation  # noqa: F401
from tests.test_postgres_inventory_receipt_posting import pytestmark, receipt_database  # noqa: F401


def test_native_multi_register_refuses_without_changes_and_single_register_still_posts(asset_runtime) -> None:  # noqa: F811
    register = AssetRegister(
        register_code="STATUTORY", cost_minor=10101, salvage_minor=1001, useful_life_months=3,
        asset_account_code="FIXED", accumulated_depreciation_account_code="ACCUM",
        accumulated_impairment_account_code="ACCUM", depreciation_expense_account_code="DEPRECIATION",
        impairment_loss_account_code="LOSS", gain_account_code="GAIN", loss_account_code="LOSS",
    )
    request = MultiRegisterAssetAcquisition(
        workspace_id="work", organization_id="org", legal_entity_id="entity", organization_code="ORG", entity_code="ENTITY",
        asset_number="QA-MULTI", name="Synthetic multi register machine", journal_code="STOCK", period_id="period",
        posting_date="2026-10-01", in_service_date="2026-10-01", cash_account_code="CASH",
        registers=(register, replace(register, register_code="TAX", cost_minor=9901)),
    )
    runtime = asset_runtime
    with runtime.actor("maker") as (connection, _receipts, actor):
        from psycopg import sql

        repository = PostgresFixedAssetsRepository(connection, runtime.tenant)

        def snapshot():
            return {table: connection.execute(sql.SQL(
                "SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY to_jsonb(r)::text),'[]'::jsonb)::text rows "
                "FROM reconforge.{} r WHERE tenant_id=%s"
            ).format(sql.Identifier(table)), (runtime.tenant,)).fetchone()["rows"] for table in (
                "fixed_assets", "fixed_asset_plans", "fixed_asset_reviews", "fixed_asset_links", "fixed_asset_commands",
                "fixed_asset_register_states", "finance_entries", "finance_entry_lines", "finance_entry_line_dimensions",
                "finance_posting_effects", "finance_posting_commands", "operational_finance_plans", "operational_finance_reviews",
                "operational_finance_links", "operational_finance_commands", "domain_audit_events", "domain_audit_ledger_state", "outbox_events",
            )}

        retained = snapshot()
        for registers in (
            request.registers,
            (register, replace(request.registers[1], cost_minor=9902)),
            tuple(reversed(request.registers)),
            (replace(register, accumulated_impairment_account_code="FIXED"), request.registers[1]),
        ):
            with pytest.raises(FinancePostingError) as failure:
                repository.acquire_multi_register(replace(request, registers=registers), command_id="qa-multi", actor=actor)
            assert failure.value.code == "asset_multi_register_owner_required"
            assert snapshot() == retained
    initial = finish(runtime, acquire(runtime))
    finish(runtime, operation(runtime, initial["asset_id"], kind="depreciate", date="2026-11-01", period="nov", month="2026-10"))
    finish(runtime, operation(runtime, initial["asset_id"], kind="depreciate", date="2027-01-01", period="jan", month="2026-12"))
    finish(runtime, operation(runtime, initial["asset_id"], kind="dispose", date="2027-01-02", period="jan", proceeds=1500))
    assert balances(runtime) == {"FIXED": 0, "ACCUM": 0, "DEPRECIATION": 9100, "CASH": -8601, "GAIN": -499}
