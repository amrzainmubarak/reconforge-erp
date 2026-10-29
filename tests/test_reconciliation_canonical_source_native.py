"""Live restricted-role proof of canonical source-field conflict handling."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from reconforge.deployment.worker_permissions import WorkerPermissionManifest
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_reconciliation import PostgresReconciliationRepository
from reconforge.workers.postgres_reconciliation import (
    LocalDeterministicMatcherAdapter,
    PostgresReconciliationWorker,
    PostgresReconciliationWorkerSettings,
)
from tests.test_reconciliation_worker_organization_native import (
    _context,
    owned_organization_database,  # noqa: F401 -- pytest fixture
)


def test_restricted_postgres_rejects_conflicts_and_accepts_consistent_source(owned_organization_database: Any) -> None:  # noqa: F811
    """Claims may fail and audit, but conflicting input never persists a match or checkpoint."""
    factory = PostgresConnectionFactory(PostgresSettings(dsn=owned_organization_database.app_dsn, require_tls=False))
    boundary = PostgresTenantBoundary(factory)
    scope = {"workspace_id": "workspace", "organization_id": "org_a", "legal_entity_id": "entity_a"}
    tenant = "org-tenant"
    manifest = WorkerPermissionManifest(
        worker_id="worker", principal_id="worker", discovery_permission="match.discover",
        execution_permission="match.run", granted_permissions=("match.discover", "match.run"),
        scope="tenant:org-tenant",
    )
    worker = PostgresReconciliationWorker(
        factory, tenant_supplier=lambda: [tenant], matcher=LocalDeterministicMatcherAdapter(),
        settings=PostgresReconciliationWorkerSettings(
            worker_id="worker", permission_manifest=manifest, discovery_policy_permission="match.discover",
            policy_context_hierarchy_supplier=_context,
        ),
    )
    # Each altered attribute used to override a contradictory stored field.
    cases: list[tuple[str, str, str, str, str, dict[str, str]]] = [
        ("amount", "1", "USD", "2026-10-28", "REF", {"amount": "999"}),
        ("currency", "999", "EUR", "2026-10-28", "REF", {"currency_code": "USD"}),
        ("date", "999", "USD", "2026-01-01", "REF", {"date": "2026-10-28"}),
        ("reference", "999", "USD", "2026-10-28", "OTHER", {"reference": "REF"}),
        ("identity", "999", "USD", "2026-10-28", "REF", {"id": "left-b"}),
        ("control", "999", "USD", "2026-10-28", "REF", {"id": "left-a", "amount": "999"}),
    ]
    for case, amount, currency, date, reference, attributes in cases:
        run_id = f"guard-{case}"
        with boundary.transaction(tenant, **scope) as db:
            repo = PostgresReconciliationRepository(db)
            repo.create_run(
                tenant_id=tenant, run_id=run_id, name="Synthetic", left_source="left", right_source="right",
                algorithm_version="synthetic-v1", rule={}, input_hash="synthetic", actor_id="maker",
            )
            rows: list[tuple[str, str, str, str, str, str, dict[str, str]]] = [
                ("Left", "left-a", amount, currency, date, reference, attributes),
                ("Right", "right-r", "999", "USD", "2026-10-28", "REF", {}),
            ]
            if case == "identity":
                # The spoofed ID exists and would pass result-reference checks.
                rows.append(("Left", "left-b", "77", "USD", "2026-10-28", "OTHER", {"id": "left-a"}))
            for side, source_id, value, code, date_value, ref, attrs in rows:
                repo.register_input(
                    tenant_id=tenant, run_id=run_id, side=side, source_id=source_id,
                    record_hash=f"hash-{source_id}", amount=value, currency_code=code,
                    date_value=date_value, reference_normalized=ref, attributes=attrs,
                )
        outcome = worker.process_run(
            tenant_id=tenant, run_id=run_id, workspace_id="workspace", organization_id="org_a", entity_id="entity_a",
        )
        with boundary.transaction(tenant, **scope) as db:
            repo = PostgresReconciliationRepository(db)
            run = repo.get_run(tenant_id=tenant, run_id=run_id)
            results = repo.list_results(tenant_id=tenant, run_id=run_id)
            exceptions = repo.list_exceptions(tenant_id=tenant, run_id=run_id)
            checkpoints = repo.list_checkpoints(tenant_id=tenant, run_id=run_id)
        if case != "control":
            assert outcome.status == "Failed", case
            assert run["execution_status"] == "Failed", case
            assert "canonical" in str(run["execution_error"]).lower(), case
            assert results == [] and exceptions == [] and checkpoints == [], case
        else:
            assert outcome.status == "Complete"
            assert len(results) == 1 and results[0]["status"] == "Matched"
            assert results[0]["left_id"] == "left-a" and results[0]["right_id"] == "right-r"
            assert Decimal(results[0]["amount_difference"]) == Decimal("0")


owned_stream_database = pytest.fixture(scope="module")(owned_organization_database.__wrapped__)


@pytest.mark.parametrize(("name", "rule", "attributes", "allowed"), [
        ("department-text", {"partition_fields": ["department"]}, {"department": "A"}, True),
        ("department-null", {"partition_fields": ["department"]}, {"department": None}, True),
        ("department-missing", {"partition_fields": ["department"]}, {}, True),
        ("department-number", {"partition_fields": ["department"]}, {"department": 1}, False),
        ("department-bool", {"partition_fields": ["department"]}, {"department": True}, False),
        ("department-number-text", {"partition_fields": ["department"]}, {"department": "1"}, True),
        ("department-bool-text", {"partition_fields": ["department"]}, {"department": "true"}, True),
        ("currency-present", {"partition_fields": ["currency"]}, {"currency": "USD"}, True),
        ("currency-missing", {"partition_fields": ["currency"]}, {}, False),
        ("currency-right-missing", {"partition_fields": ["currency"]}, {"currency": "USD"}, False),
        ("ccy-present", {"partition_fields": ["ccy"]}, {"ccy": "USD"}, True),
        ("ccy-missing", {"partition_fields": ["ccy"]}, {}, False),
        ("ccy-right-missing", {"partition_fields": ["ccy"]}, {"ccy": "USD"}, False),
        ("currency-code", {"partition_fields": ["currency_code"]}, {}, True),
        ("amount-unsupported", {"partition_fields": ["amount"]}, {}, False),
        ("date-value", {"partition_fields": ["date_value"], "date_field": "date_value"}, {}, True),
])
def test_streamed_postgres_partition_values_keep_sql_and_matcher_identity(
    owned_stream_database: Any, name: str, rule: dict[str, object], attributes: dict[str, object], allowed: bool,
) -> None:
    """Exercise real SQL cursor keys, including JSON types and PostgreSQL DATE."""
    factory = PostgresConnectionFactory(PostgresSettings(dsn=owned_stream_database.app_dsn, require_tls=False))
    boundary = PostgresTenantBoundary(factory)
    scope = {"workspace_id": "workspace", "organization_id": "org_a", "legal_entity_id": "entity_a"}
    tenant = "org-tenant"
    manifest = WorkerPermissionManifest(
        worker_id="worker", principal_id="worker", discovery_permission="match.discover",
        execution_permission="match.run", granted_permissions=("match.discover", "match.run"),
        scope="tenant:org-tenant",
    )
    worker = PostgresReconciliationWorker(
        factory, tenant_supplier=lambda: [tenant], matcher=LocalDeterministicMatcherAdapter(),
        settings=PostgresReconciliationWorkerSettings(
            worker_id="worker", permission_manifest=manifest, discovery_policy_permission="match.discover",
            policy_context_hierarchy_supplier=_context,
        ),
    )
    run_id = "stream-" + name
    with boundary.transaction(tenant, **scope) as db:
        repo = PostgresReconciliationRepository(db)
        repo.create_run(
            tenant_id=tenant, run_id=run_id, name="Synthetic", left_source="left", right_source="right",
            algorithm_version="synthetic-v1", rule=rule, input_hash="synthetic", actor_id="maker",
        )
        for side, source_id in (("Left", "left-a"), ("Right", "right-r")):
            selected_attributes = {} if side == "Right" and name in {"currency-right-missing", "ccy-right-missing"} else attributes
            repo.register_input(
                tenant_id=tenant, run_id=run_id, side=side, source_id=source_id,
                record_hash=f"hash-{source_id}", amount="10", currency_code="USD",
                date_value="2026-10-28", reference_normalized="REF", attributes=selected_attributes,
            )
        if name == "date-value":
            from datetime import date

            assert all(type(row["date_value"]) is date for row in repo.list_inputs(tenant_id=tenant, run_id=run_id))
    outcome = worker.process_run(
        tenant_id=tenant, run_id=run_id, workspace_id="workspace", organization_id="org_a", entity_id="entity_a",
    )
    with boundary.transaction(tenant, **scope) as db:
        repo = PostgresReconciliationRepository(db)
        run = repo.get_run(tenant_id=tenant, run_id=run_id)
        results = repo.list_results(tenant_id=tenant, run_id=run_id)
        exceptions = repo.list_exceptions(tenant_id=tenant, run_id=run_id)
        checkpoints = repo.list_checkpoints(tenant_id=tenant, run_id=run_id)
    assert exceptions == [], name
    if allowed:
        assert outcome.status == run["execution_status"] == "Complete", (name, run["execution_error"])
        assert len(results) == 1 and results[0]["status"] == "Matched", name
        assert (results[0]["left_id"], results[0]["right_id"]) == ("left-a", "right-r"), name
        assert len(checkpoints) == 1, name
    else:
        assert outcome.status == run["execution_status"] == "Failed", name
        assert "partition" in str(run["execution_error"]).lower() or "alias" in str(run["execution_error"]).lower(), name
        assert results == [] and checkpoints == [], name


def test_streamed_failure_does_not_rewrite_previously_committed_partition(
    owned_stream_database: Any,
) -> None:
    """A later invalid key may fail after an earlier checkpoint is committed."""
    factory = PostgresConnectionFactory(PostgresSettings(dsn=owned_stream_database.app_dsn, require_tls=False))
    boundary = PostgresTenantBoundary(factory)
    scope = {"workspace_id": "workspace", "organization_id": "org_a", "legal_entity_id": "entity_a"}
    tenant, run_id = "org-tenant", "stream-late-invalid"
    with boundary.transaction(tenant, **scope) as db:
        repo = PostgresReconciliationRepository(db)
        repo.create_run(
            tenant_id=tenant, run_id=run_id, name="Synthetic", left_source="left", right_source="right",
            algorithm_version="synthetic-v1", rule={"partition_fields": ["department"]},
            input_hash="synthetic", actor_id="maker",
        )
        for department, suffix in (("A", "good"), ("Z\n", "bad")):
            for side, label in (("Left", "left"), ("Right", "right")):
                source_id = f"{label}-{suffix}"
                repo.register_input(
                    tenant_id=tenant, run_id=run_id, side=side, source_id=source_id,
                    record_hash=f"hash-{source_id}", amount="10", currency_code="USD",
                    date_value="2026-10-28", reference_normalized="REF", attributes={"department": department},
                )
    manifest = WorkerPermissionManifest(
        worker_id="worker", principal_id="worker", discovery_permission="match.discover",
        execution_permission="match.run", granted_permissions=("match.discover", "match.run"),
        scope="tenant:org-tenant",
    )
    worker = PostgresReconciliationWorker(
        factory, tenant_supplier=lambda: [tenant], matcher=LocalDeterministicMatcherAdapter(),
        settings=PostgresReconciliationWorkerSettings(
            worker_id="worker", permission_manifest=manifest, discovery_policy_permission="match.discover",
            policy_context_hierarchy_supplier=_context,
        ),
    )
    outcome = worker.process_run(
        tenant_id=tenant, run_id=run_id, workspace_id="workspace", organization_id="org_a", entity_id="entity_a",
    )
    with boundary.transaction(tenant, **scope) as db:
        repo = PostgresReconciliationRepository(db)
        run = repo.get_run(tenant_id=tenant, run_id=run_id)
        results = repo.list_results(tenant_id=tenant, run_id=run_id)
        checkpoints = repo.list_checkpoints(tenant_id=tenant, run_id=run_id)
        exceptions = repo.list_exceptions(tenant_id=tenant, run_id=run_id)
    assert outcome.status == run["execution_status"] == "Failed"
    assert "partition" in str(run["execution_error"]).lower()
    assert len(checkpoints) == 1 and len(results) == 1 and exceptions == []
    assert (results[0]["left_id"], results[0]["right_id"]) == ("left-good", "right-good")
