"""Independent ordinary-app counterexamples for remaining-original allocation.

Collection and pure models do not qualify these tests as executed. Every test
uses native originals and retains all 79 financial tables around a refusal.
Assertions expose constant diagnostics instead of private PostgreSQL row text.
"""
from __future__ import annotations

from typing import Any

import psycopg
import pytest
from psycopg import sql

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_customer_partial_returns import PostgresCustomerPartialReturnsRepository
from reconforge.platform.common import current_server_principal, server_principal_context
from tests.customer_partial_return_posted_cycle_oracle import TABLES, require
from tests.test_postgres_customer_partial_return_rounding import (
    create_remainder_runtime,
    phase_v2,
    post_v2,
    prepare_v2,
)
from tests.test_postgres_customer_partial_returns import phase, prepare_return, request
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, receipt_database

_ = receipt_database
ROUNDING_TABLES = (*TABLES, "customer_partial_return_allocation_witnesses")


def capture_rounding(runtime: ReceiptRuntime) -> dict[str, tuple[str, ...]]:
    with runtime.actor("maker") as (connection, _, _actor):
        return {name: tuple(row["original"] for row in connection.execute(
            sql.SQL('SELECT to_jsonb(r)::text original FROM reconforge.{} r WHERE tenant_id=%s ORDER BY to_jsonb(r)::text COLLATE "C"')
            .format(sql.Identifier(name)), (runtime.tenant,)).fetchall()) for name in ROUNDING_TABLES}


def check_cause(error: BaseException) -> psycopg.errors.CheckViolation:
    """Inspect the owner's exact cause without accepting an unrelated refusal."""
    cause: BaseException | None = error
    for _ in range(8):
        if isinstance(cause, psycopg.errors.CheckViolation):
            return cause
        cause = cause.__cause__ if cause is not None else None
    raise AssertionError("The expected native CHECK cause was not retained.")


def test_zero_plan_row_check_requires_explicit_v2_schema_and_nonnull_literal_policy(
    receipt_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, source = create_remainder_runtime(receipt_database, zero=True)
    control = prepare_v2(runtime, source, 1, 0, "C-ZERO-CHECK-CONTROL")
    require(control["amount_minor"] == 0 and control["entries"] == [])
    phase_v2(runtime, control, "cancel", "checker")
    with runtime.actor("maker") as (connection, _, _actor):
        constraints = connection.execute("""SELECT conname FROM pg_constraint
            WHERE conrelid='reconforge.customer_partial_return_plans'::regclass AND contype='c'
            AND pg_get_constraintdef(oid) LIKE '%%allocation_policy%%'
            AND pg_get_constraintdef(oid) LIKE '%%credit_minor%%'""").fetchall()
    require(len(constraints) == 1)
    expected_constraint = constraints[0]["conname"]
    real_save = PostgresCustomerPartialReturnsRepository._save
    for attack in ("missing-policy", "null-policy", "invalid-policy", "missing-schema", "fake-v1"):
        before = capture_rounding(runtime)

        def malformed(self: Any, payload: dict[str, Any], actor: Any, attack: str = attack) -> None:
            require(payload["amount_minor"] == 0 and payload["entries"] == [])
            if attack == "missing-policy":
                payload.pop("allocation_policy")
            elif attack == "null-policy":
                payload["allocation_policy"] = None
            elif attack == "invalid-policy":
                payload["allocation_policy"] = "unapproved-current-policy"
            elif attack == "missing-schema":
                payload.pop("schema_version")
            else:
                payload["schema_version"] = "customer-partial-return-v1"
            real_save(self, payload, actor)

        with monkeypatch.context() as adversary:
            adversary.setattr(PostgresCustomerPartialReturnsRepository, "_save", malformed)
            with pytest.raises(FinancePostingError) as denied, runtime.actor("maker") as (connection, _, actor):
                owner = PostgresCustomerPartialReturnsRepository(connection, runtime.tenant, protocol_version=2)
                owner.prepare(request(source, 1, 0), command_id="C-ZERO-CHECK-" + attack, actor=actor)
        require(check_cause(denied.value).diag.constraint_name == expected_constraint)
        require(capture_rounding(runtime) == before)


def test_same_zero_rounding_result_cannot_hide_a_forged_original_before_value(
    receipt_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, source = create_remainder_runtime(receipt_database, zero=True)
    control = prepare_v2(runtime, source, 1, 0, "C-ZERO-WITNESS-CONTROL")
    phase_v2(runtime, control, "cancel", "checker")
    before = capture_rounding(runtime)
    real_save = PostgresCustomerPartialReturnsRepository._save

    def forged(self: Any, payload: dict[str, Any], actor: Any) -> None:
        require(payload["cogs_restored_minor"] == 0 and payload["domain_plan"]["portions"][0]["before_value_minor"] == 1)
        # Both 1/3 and forged 0/3 round to zero. Equality of the monetary
        # result cannot substitute for exact immutable original-prefix facts.
        payload["domain_plan"]["portions"][0]["before_value_minor"] = 0
        real_save(self, payload, actor)

    with monkeypatch.context() as adversary:
        adversary.setattr(PostgresCustomerPartialReturnsRepository, "_save", forged)
        with pytest.raises(psycopg.errors.CheckViolation) as denied, runtime.actor("maker") as (connection, _, actor):
            owner = PostgresCustomerPartialReturnsRepository(connection, runtime.tenant, protocol_version=2)
            owner.prepare(request(source, 1, 0), command_id="C-FORGED-ZERO-BEFORE", actor=actor)
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    require(denied.value.diag.constraint_name == "customer_partial_return_owner")
    require(denied.value.diag.message_primary == "V2 prepared allocation must retain its exact original prefix")
    require(capture_rounding(runtime) == before)


def test_version_two_cannot_upgrade_a_source_already_born_under_version_one(receipt_database: tuple[str, str]) -> None:
    runtime, source = create_remainder_runtime(receipt_database)
    # Full original quantity/cost is a valid v1 control, with no fractional cut.
    legacy = prepare_return(runtime, source, 3, 0, "C-LEGACY-BIRTH")
    require(legacy["schema_version"] == "customer-partial-return-v1" and legacy["cogs_restored_minor"] == 1001)
    phase(runtime, legacy, "cancel", "checker")
    before = capture_rounding(runtime)
    with pytest.raises(FinancePostingError) as denied, runtime.actor("maker") as (connection, _, actor):
        PostgresCustomerPartialReturnsRepository(connection, runtime.tenant, protocol_version=2).prepare(
            request(source, 3, 0), command_id="C-NO-SILENT-UPGRADE", actor=actor)
    require(denied.value.code == "customer_partial_return_protocol_conflict")
    require(capture_rounding(runtime) == before)


def test_posted_zero_witness_cannot_authorize_a_new_unowned_zero_layer_change(receipt_database: tuple[str, str]) -> None:
    runtime, source = create_remainder_runtime(receipt_database, zero=True)
    plan = post_v2(runtime, prepare_v2(runtime, source, 1, 0, "C-POSTED-ZERO"))
    require(plan["phase"] == 2 and plan["entries"] == [])
    before = capture_rounding(runtime)
    with runtime.actor("poster") as (connection, _, _actor):
        rows = connection.execute("""SELECT r.cost_layer_id,l.remaining_quantity_scaled,l.remaining_value_minor
            FROM reconforge.customer_partial_return_restorations r JOIN reconforge.inventory_cost_layers l
            ON(l.tenant_id,l.id)=(r.tenant_id,r.cost_layer_id)
            WHERE r.tenant_id=%s AND r.plan_id=%s""", (runtime.tenant, plan["id"])).fetchall()
    require(len(rows) == 1 and rows[0]["remaining_quantity_scaled"] == 1 and rows[0]["remaining_value_minor"] == 0)
    with pytest.raises(psycopg.errors.CheckViolation) as denied, runtime.actor("poster") as (connection, _, actor):
        connection.execute("SELECT set_config('app.customer_partial_return_actor_id',%s,true)", (actor.user_id,))
        connection.execute("""UPDATE reconforge.inventory_cost_layers SET remaining_quantity_scaled=remaining_quantity_scaled+1
            WHERE tenant_id=%s AND id=%s""", (runtime.tenant, rows[0]["cost_layer_id"]))
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    require(denied.value.diag.constraint_name == "customer_partial_return_owner")
    require(denied.value.diag.message_primary == "A zero-value physical layer requires its exact visible native allocation witness")
    require(capture_rounding(runtime) == before)


def test_supplemental_witnesses_inherit_all_four_parent_scope_boundaries_and_are_immutable(receipt_database: tuple[str, str]) -> None:
    runtime, source = create_remainder_runtime(receipt_database, zero=True)
    plan = post_v2(runtime, prepare_v2(runtime, source, 1, 0, "C-WITNESS-RLS"))
    before = capture_rounding(runtime)
    require(len(before["customer_partial_return_allocation_witnesses"]) == 1)
    for scope_key in ("tenant_id", "workspace_id", "organization_id", "legal_entity_id"):
        with runtime.actor("maker") as (connection, _, _actor):
            query = "SELECT count(*) n FROM reconforge.customer_partial_return_allocation_witnesses WHERE tenant_id=%s AND plan_id=%s"
            require(connection.execute(query, (runtime.tenant, plan["id"])).fetchone()["n"] == 1)
            connection.execute("SELECT set_config(%s,%s,true)", ("app." + scope_key, "hidden-sibling-scope"))
            require(connection.execute(query, (runtime.tenant, plan["id"])).fetchone()["n"] == 0)
    for operation in ("UPDATE", "DELETE"):
        with pytest.raises(psycopg.errors.CheckViolation) as denied, runtime.actor("poster") as (connection, _, _actor):
            if operation == "UPDATE":
                connection.execute("""UPDATE reconforge.customer_partial_return_allocation_witnesses SET before_value_minor=0
                    WHERE tenant_id=%s AND plan_id=%s""", (runtime.tenant, plan["id"]))
            else:
                connection.execute("DELETE FROM reconforge.customer_partial_return_allocation_witnesses WHERE tenant_id=%s AND plan_id=%s",
                                   (runtime.tenant, plan["id"]))
        require(denied.value.diag.constraint_name == "customer_partial_return_owner")
        require(denied.value.diag.message_primary == "Original allocation witness is immutable")
        require(capture_rounding(runtime) == before)


def test_zero_effect_cached_ack_rechecks_current_posting_authority(receipt_database: tuple[str, str]) -> None:
    runtime, source = create_remainder_runtime(receipt_database, zero=True)
    reviewed = phase_v2(runtime, prepare_v2(runtime, source, 1, 0, "C-ZERO-AUTHORITY"), "review", "checker")
    actual = phase_v2(runtime, reviewed, "post", "poster")
    require(actual["phase"] == 2 and actual["entries"] == [])
    before = capture_rounding(runtime)
    require(phase_v2(runtime, reviewed, "post", "poster") == actual)
    require(capture_rounding(runtime) == before)
    with runtime.actor("poster") as (_connection, _, cached_actor):
        principal = current_server_principal()
    if principal is None:
        raise AssertionError("The authenticated native poster is required.")
    with runtime.actor("maker") as (connection, _, actor):
        connection.execute("""UPDATE reconforge.identity_role_permissions SET active=FALSE,revoked_at=now(),revoked_by=%s,
            revocation_reason_code='access_change',lifecycle_version=lifecycle_version+1
            WHERE tenant_id=%s AND permission_name='finance_core.post'""", (actor.user_id, runtime.tenant))
    before = capture_rounding(runtime)
    with pytest.raises(FinancePostingError) as denied, PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant,
            workspace_id="work", organization_id="org", legal_entity_id="entity") as connection, server_principal_context(principal):
        PostgresCustomerPartialReturnsRepository(connection, runtime.tenant, protocol_version=2).post(reviewed["id"],
            expected_plan_digest=reviewed["plan_digest"], command_id=reviewed["id"] + ":post",
            reason="Actual remaining-value post", actor=cached_actor)
    require(denied.value.code == "operational_actor_denied")
    require(capture_rounding(runtime) == before)
