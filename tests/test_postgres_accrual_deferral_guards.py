"""Actual source SQL refusal, current authority and period governance."""

from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError, canonical_json
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_master_data import PostgresMasterDataRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.test_postgres_accrual_deferral import (
    ScheduleRuntime,
    accrual_deferral_database,
    preparation,
    publish,
    pytestmark,
    receipt_database,
    runtime,
)

__all__ = ["accrual_deferral_database", "pytestmark", "receipt_database", "runtime"]


def retained_state(rt: ScheduleRuntime) -> dict[str, Any]:
    from psycopg import sql

    with rt.actor("maker") as (connection, _, _):
        return {table: connection.execute(sql.SQL("SELECT COALESCE(jsonb_agg(to_jsonb(row_) ORDER BY to_jsonb(row_)::text),'[]'::jsonb) AS data FROM (SELECT * FROM reconforge.{} WHERE tenant_id=%s) row_").format(sql.Identifier(table)),
            (rt.base.tenant,)).fetchone()["data"] for table in (
                "accrual_deferral_sources", "accrual_deferral_plans", "accrual_deferral_claim_heads", "accrual_deferral_claim_events",
                "accrual_deferral_phase_events", "accrual_deferral_commands", "finance_entries", "finance_entry_lines",
                "finance_posting_effects", "domain_audit_events", "outbox_events")}


@pytest.mark.parametrize("mutation", ["source_amount", "source_dimensions", "plan_amount", "skip_phase", "missing_claim_event", "command_body", "remove_pin"])
def test_direct_sql_source_history_and_missing_claim_event_refusal_roll_back_whole_population(runtime: ScheduleRuntime, mutation: str) -> None:
    import psycopg

    with runtime.actor("maker") as (_, repository, actor):
        plan = repository.prepare_source(preparation("expense_accrual"), command_id="guard-source", actor=actor)
    before = retained_state(runtime)
    with pytest.raises(psycopg.IntegrityError), runtime.actor("maker") as (connection, _, _):
        if mutation == "source_amount":
            connection.execute("UPDATE reconforge.accrual_deferral_sources SET payload=jsonb_set(payload,'{request,amount_minor}','10002') WHERE tenant_id=%s AND id=%s", (runtime.base.tenant, plan["source_id"]))
        elif mutation == "source_dimensions":
            connection.execute("UPDATE reconforge.accrual_deferral_sources SET payload=jsonb_set(payload,'{equation,external_original_membership,basis_dimensions}','{\"FORGED\":\"PROJECT\"}') WHERE tenant_id=%s AND id=%s", (runtime.base.tenant, plan["source_id"]))
        elif mutation == "plan_amount":
            connection.execute("UPDATE reconforge.accrual_deferral_plans SET payload=jsonb_set(payload,'{equation,amount_minor}','10002') WHERE tenant_id=%s AND id=%s", (runtime.base.tenant, plan["id"]))
        elif mutation == "skip_phase":
            connection.execute("UPDATE reconforge.accrual_deferral_plans SET phase=2 WHERE tenant_id=%s AND id=%s", (runtime.base.tenant, plan["id"]))
        elif mutation == "missing_claim_event":
            assert connection.execute("UPDATE reconforge.accrual_deferral_claim_heads SET sequence=sequence+1 WHERE tenant_id=%s AND source_id=%s AND tranche_id='T1' RETURNING sequence", (runtime.base.tenant, plan["source_id"])).rowcount == 1
        elif mutation == "command_body":
            connection.execute("UPDATE reconforge.accrual_deferral_commands SET request_json='{}' WHERE tenant_id=%s AND plan_id=%s", (runtime.base.tenant, plan["id"]))
        else:
            connection.execute("DELETE FROM reconforge.accrual_deferral_account_pins WHERE tenant_id=%s AND source_id=%s", (runtime.base.tenant, plan["source_id"]))
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert retained_state(runtime) == before


@pytest.mark.parametrize("dimensions", [{"D" + str(index): "V" for index in range(9)}, {"D": 1}, {" D": "V"}, {"D": ""}])
def test_canonical_native_line_refuses_unbounded_or_malformed_dimension_capture(runtime: ScheduleRuntime, dimensions: dict[str, Any]) -> None:
    import psycopg

    with runtime.actor("maker") as (connection, _, _):
        exact = {"D" + str(index): "V" + str(index) for index in range(8)}
        assert connection.execute("SELECT reconforge.ad1_line('EXPENSE',9000000000000000000,0,%s::jsonb) AS result", (canonical_json(exact),)).fetchone()["result"]["dimensions"] == exact
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute("SELECT reconforge.ad1_line('EXPENSE',1,0,%s::jsonb)", (canonical_json(dimensions),))


@pytest.mark.parametrize("operation", ["get", "source", "evidence", "members"])
@pytest.mark.parametrize("revoked", ["scope", "permission"])
def test_cached_principal_reads_refuse_current_persisted_scope_revocation(runtime: ScheduleRuntime, accrual_deferral_database: tuple[str, str], operation: str, revoked: str) -> None:
    import psycopg

    with runtime.actor("maker") as (_, repository, actor):
        plan = repository.prepare_source(preparation("expense_accrual"), command_id="scope-source", actor=actor)
    with runtime.actor("maker") as (_, repository, actor):
        with psycopg.connect(accrual_deferral_database[0]) as admin:
            if revoked == "scope":
                PostgresScopeAuthorityRepository(admin).revoke(tenant_id=runtime.base.tenant, grant_id="ad1-makerentity", actor_id="poster", reason="Synthetic current source-read authority revocation")
            else:
                admin.execute("UPDATE reconforge.identity_role_permissions SET active=false,lifecycle_version=lifecycle_version+1,revoked_at=now(),revoked_by='poster',revocation_reason_code='access_change' WHERE tenant_id=%s AND permission_name='accrual_deferral.read'", (runtime.base.tenant,))
        with pytest.raises(FinancePostingError) as refused:
            if operation == "get":
                repository.get_plan(plan["id"], actor=actor)
            elif operation == "source":
                repository.get_source(plan["source_id"], actor=actor)
            elif operation == "evidence":
                repository.evidence(plan["source_id"], actor=actor)
            else:
                repository.plan_evidence(plan["id"], actor=actor)
        assert "denied" in refused.value.code


@pytest.mark.parametrize("operation", ["get", "source", "evidence", "members"])
@pytest.mark.parametrize("permission", ["accrual_deferral.read", "finance_core.read"])
def test_every_source_read_supplies_exact_amount_and_precision_to_its_separate_central_policy(runtime: ScheduleRuntime,
        operation: str, permission: str, monkeypatch) -> None:
    from decimal import Decimal

    import reconforge.infrastructure.postgres_operational_finance as native_owner
    from reconforge.auth.policy import evaluate_principal_access

    with runtime.actor("maker") as (_, repository, actor):
        plan = repository.prepare_source(preparation("expense_accrual"), command_id="amount-source", actor=actor)
    observed = []

    def bounded(principal, **context):
        amount = context.get("amount")
        if context["required_permission"] == permission and amount is not None:
            observed.append(amount)
            return evaluate_principal_access(principal, maximum_amount=Decimal("50.00"), **context)
        return evaluate_principal_access(principal, **context)

    monkeypatch.setattr(native_owner, "evaluate_principal_access", bounded)
    with runtime.actor("maker") as (_, repository, actor), pytest.raises(FinancePostingError) as refused:
        if operation == "get":
            repository.get_plan(plan["id"], actor=actor)
        elif operation == "source":
            repository.get_source(plan["source_id"], actor=actor)
        elif operation == "evidence":
            repository.evidence(plan["source_id"], actor=actor)
        else:
            repository.plan_evidence(plan["id"], actor=actor)
    assert "denied" in refused.value.code and observed == [Decimal("100.01")]


def test_reasoned_native_period_close_refuses_new_phase_then_reopen_preserves_source(runtime: ScheduleRuntime) -> None:
    with runtime.actor("maker") as (_, repository, actor):
        plan = repository.prepare_source(preparation("expense_accrual"), command_id="period-source", actor=actor)
    with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant, workspace_id="work") as connection:
        masters = PostgresMasterDataRepository(connection)
        for status in ("Soft Closed", "Closed"):
            masters.set_period_status(tenant_id=runtime.base.tenant, period_id="period", status=status, reason="Reviewed native fiscal close", actor_id="poster")
    before = retained_state(runtime)
    with pytest.raises(FinancePostingError), runtime.actor("checker") as (_, repository, actor):
        repository.review(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Closed native period cannot admit a new phase", command_id="closed-review", actor=actor)
    assert retained_state(runtime) == before
    with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant, workspace_id="work") as connection:
        PostgresMasterDataRepository(connection).set_period_status(tenant_id=runtime.base.tenant, period_id="period", status="Open", reason="Reasoned native period reopen for the exact retained source", actor_id="poster")
    posted = publish(runtime, plan, "reopened")
    assert posted["phase"] == 2 and posted["posting_effect_id"] is None


def test_every_inverse_review_rechecks_current_reverse_permission_and_rolls_back(runtime: ScheduleRuntime, accrual_deferral_database: tuple[str, str]) -> None:
    import psycopg

    with runtime.actor("maker") as (_, repository, actor):
        plan = repository.prepare_source(preparation(), command_id="reverse-source", actor=actor)
    source = publish(runtime, plan, "reverse-source")
    with runtime.actor("maker") as (_, repository, actor):
        tranche = repository.prepare_tranche(source["source_id"], tranche_id="T1", command_id="reverse-tranche", actor=actor)
    tranche = publish(runtime, tranche, "reverse-tranche")
    with runtime.actor("maker") as (_, repository, actor):
        inverse = repository.prepare_reversal(source["source_id"], original_plan_id=tranche["id"], period_id="p2", posting_date="2026-11-01", reason="Exact inverse awaits current reverse authority", command_id="reverse-inverse", actor=actor)
    before = retained_state(runtime)
    with runtime.actor("checker") as (connection, repository, actor):
        with psycopg.connect(accrual_deferral_database[0]) as admin:
            admin.execute("UPDATE reconforge.identity_role_permissions SET active=false,lifecycle_version=lifecycle_version+1,revoked_at=now(),revoked_by='poster',revocation_reason_code='access_change' WHERE tenant_id=%s AND permission_name='finance_core.reverse'", (runtime.base.tenant,))
        with pytest.raises(FinancePostingError) as refused:
            repository.review(inverse["id"], expected_plan_digest=inverse["plan_digest"], reason="Revoked original reverse admission", command_id="reverse-denied", actor=actor)
        assert "denied" in refused.value.code
        with pytest.raises(psycopg.errors.CheckViolation, match="current persisted native reverse permission"), connection.transaction():
            # Retained inverse/source/actor/scope is real. The persisted SQL
            # guard must reject before any deferred response-body closure,
            # even when a caller bypasses the application owner method.
            connection.execute("""INSERT INTO reconforge.accrual_deferral_commands
                (tenant_id,workspace_id,organization_id,legal_entity_id,plan_id,operation,command_id,actor_id,request_digest,request_json,response_json)
                SELECT tenant_id,workspace_id,organization_id,legal_entity_id,plan_id,'review','direct-reverse-review','checker',request_digest,request_json,response_json
                FROM reconforge.accrual_deferral_commands WHERE tenant_id=%s AND plan_id=%s AND operation='prepare'""",
                (runtime.base.tenant, inverse["id"]))
    assert retained_state(runtime) == before
