"""Actual ordered native IC2 originals; source cashflow creates no effects."""

from dataclasses import replace
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.intercompany_cashflow import SourceCashOpening
from reconforge.infrastructure.postgres_intercompany_cashflow import PostgresIntercompanyCashflowRepository
from tests.test_postgres_intercompany_fx import (
    FxRuntime,
    backing_digest,
    cash,
    eliminate,
    intercompany_fx_database,
    receipt_database,
    recognize,
    revalue,
    runtime,
)

__all__ = ["intercompany_fx_database", "receipt_database", "runtime"]
pytest_plugins = ("tests.test_postgres_intercompany_fx",)


def opening(rt: FxRuntime, plan: dict[str, Any]) -> SourceCashOpening:
    with rt.actor("poster") as (_, repository, actor):
        source = repository.evidence(plan["id"], actor=actor)["source"]
    return SourceCashOpening(source["id"], source["source_digest"], plan["id"], plan["plan_digest"], 0, 0,
        "complete-native-source-origin-membership")


def write_original(value: dict[str, Any]) -> None:
    import json
    import os
    from pathlib import Path
    from uuid import uuid4

    if directory := os.environ.get("RECONFORGE_CASHFLOW_PROOF_DIR"):
        path = Path(directory, "original-cashflow-" + uuid4().hex + ".json")
        with path.open("x", encoding="utf8") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def test_actual_native_partial_cycle_cashflow_and_explicit_opening_refusals_leave_gl_unchanged(runtime: FxRuntime) -> None:
    original = recognize(runtime)
    basis = opening(runtime, original)
    cash(runtime, original["source_id"])
    revalue(runtime, original["source_id"])
    eliminate(runtime, original["source_id"])
    with runtime.actor("poster") as (connection, _, actor):
        before = backing_digest(connection, runtime.base.tenant)
        repository = PostgresIntercompanyCashflowRepository(connection, runtime.base.tenant)
        proof = repository.evidence(original["source_id"], opening=basis, actor=actor)
        assert proof["cashflow"]["operating_net_minor"] == 0
        assert proof["cashflow"]["fx_on_cash_minor"] == proof["cashflow"]["closing_minor"] == 101
        assert proof["cashflow"]["books"]["seller"]["fx_on_cash_minor"] == -45
        assert proof["cashflow"]["books"]["buyer"]["fx_on_cash_minor"] == 146
        assert proof["native_role"] == {"rolsuper": False, "rolbypassrls": False}
        assert repository.evidence(original["source_id"], opening=basis, actor=actor) == proof
        for change in ({"seller_minor": 1}, {"buyer_minor": None}, {"basis": "unknown-opening"},
                       {"origin_plan_digest": "0" * 64}, {"source_id": "another-source"}):
            with pytest.raises(FinancePostingError, match="explicit known zero opening"):
                repository.evidence(original["source_id"], opening=replace(basis, **change), actor=actor)
        assert backing_digest(connection, runtime.base.tenant) == before
        assert len(proof["original_rows"]["effects"]) == 7
        write_original(proof)


def test_unfinished_actual_native_source_cannot_default_cashflow_to_zero(runtime: FxRuntime) -> None:
    original = recognize(runtime)
    basis = opening(runtime, original)
    with runtime.actor("poster") as (connection, _, actor):
        before = backing_digest(connection, runtime.base.tenant)
        with pytest.raises(FinancePostingError, match="complete posted IC2 source"):
            PostgresIntercompanyCashflowRepository(connection, runtime.base.tenant).evidence(
                original["source_id"], opening=basis, actor=actor)
        assert backing_digest(connection, runtime.base.tenant) == before


def test_cached_actor_cannot_export_after_current_native_group_grant_revocation(runtime: FxRuntime) -> None:
    import psycopg

    original = recognize(runtime)
    basis = opening(runtime, original)
    cash(runtime, original["source_id"])
    revalue(runtime, original["source_id"])
    eliminate(runtime, original["source_id"])
    with runtime.actor("poster") as (connection, _, actor):
        before = backing_digest(connection, runtime.base.tenant)
        with psycopg.connect(runtime.base.admin_dsn) as admin:
            admin.execute("""UPDATE reconforge.principal_scope_grants SET revoked_at=now(),revoked_by='maker',
                revocation_reason='Current group reporting access withdrawn' WHERE tenant_id=%s
                AND principal_id='poster' AND scope_type='legal_entity' AND scope_id='group'""", (runtime.base.tenant,))
        with pytest.raises(FinancePostingError) as refused:
            PostgresIntercompanyCashflowRepository(connection, runtime.base.tenant).evidence(
                original["source_id"], opening=basis, actor=actor)
        assert "denied" in refused.value.code
        assert backing_digest(connection, runtime.base.tenant) == before
