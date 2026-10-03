"""Restricted PostgreSQL callers cannot extend a sealed reconciliation manifest."""
from __future__ import annotations

import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from time import monotonic, sleep
from typing import Any

import pytest

from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresRuntimeConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    set_local_tenant_scope,
)
from reconforge.infrastructure.postgres_reconciliation import PostgresReconciliationRepository
from tests.test_alembic_postgres import isolated_postgres_migration_dsn as _isolated_postgres_migration_dsn

isolated_postgres_migration_dsn = _isolated_postgres_migration_dsn
TENANT = "input-seal-synthetic"


@pytest.fixture
def seal_database(isolated_postgres_migration_dsn: str):
    import psycopg
    from alembic.config import Config

    from alembic import command

    app_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_DSN")
    if not app_dsn:
        pytest.skip("requires a restricted PostgreSQL application role")
    config = Config(str(Path("alembic.ini").resolve()))
    command.upgrade(config, "head")
    params = psycopg.conninfo.conninfo_to_dict(app_dsn)
    params["dbname"] = psycopg.conninfo.conninfo_to_dict(isolated_postgres_migration_dsn)["dbname"]
    with psycopg.connect(isolated_postgres_migration_dsn) as admin:
        role = psycopg.sql.Identifier(params["user"])
        admin.execute(psycopg.sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(role))
        tables = ("tenants", "audit_events", "outbox_events", "reconciliation_runs", "reconciliation_inputs", "reconciliation_results", "reconciliation_exceptions", "reconciliation_execution_checkpoints")
        admin.execute(psycopg.sql.SQL("GRANT SELECT,INSERT,UPDATE ON {} TO {}").format(psycopg.sql.SQL(",").join(psycopg.sql.Identifier("reconforge", name) for name in tables), role))
        admin.execute(psycopg.sql.SQL("GRANT DELETE ON reconforge.reconciliation_inputs,reconforge.reconciliation_results,reconforge.reconciliation_exceptions TO {}").format(role))
        admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,'Synthetic input seal'),('input-seal-sibling','Synthetic sibling')", (TENANT,))
    factory = PostgresRuntimeConnectionFactory(PostgresConnectionFactory(PostgresSettings(dsn=psycopg.conninfo.make_conninfo(**params), require_tls=False)))
    try:
        yield {"admin": isolated_postgres_migration_dsn, "factory": factory, "boundary": PostgresTenantBoundary(factory), "config": config}
    finally:
        factory.close()


def _create(repository: PostgresReconciliationRepository, run: str) -> None:
    repository.create_run(tenant_id=TENANT, run_id=run, name="Synthetic input seal", left_source="left", right_source="right", algorithm_version="seal-test-v1", rule={}, input_hash="synthetic", actor_id="maker")


def _raw_insert(connection: Any, run: str, source: str = "source") -> None:
    connection.execute("INSERT INTO reconforge.reconciliation_inputs(tenant_id,run_id,side,source_id,record_hash,amount_decimal,currency_code) VALUES(%s,%s,'Left',%s,'synthetic-fingerprint',1.00,'USD')", (TENANT, run, source))


def _raw_output(connection: Any, run: str, table: str) -> None:
    if table == "results":
        connection.execute("INSERT INTO reconforge.reconciliation_results(tenant_id,id,run_id,left_id,match_type,confidence,explanation,status) VALUES(%s,%s,%s,'source','unmatched_left',0,'Synthetic output','Unmatched')", (TENANT, run + "-output", run))
    else:
        assert table == "exceptions"
        connection.execute("INSERT INTO reconforge.reconciliation_exceptions(tenant_id,id,run_id,exception_type,source_side,source_id,title,explanation,severity,risk_score,reason_code) VALUES(%s,%s,%s,'Synthetic','Left','source','Synthetic','Synthetic output','Low',0,'SYNTHETIC')", (TENANT, run + "-exception", run))


def _completed(repository: PostgresReconciliationRepository, run: str) -> dict[str, Any]:
    _create(repository, run)
    repository.register_input(tenant_id=TENANT, run_id=run, side="Left", source_id="source", record_hash="synthetic-fingerprint", amount="1.00", currency_code="USD")
    repository.append_result(tenant_id=TENANT, run_id=run, left_id="source", match_type="unmatched_left", confidence="0", explanation="Synthetic unmatched source", status="Unmatched")
    return repository.complete_run(tenant_id=TENANT, run_id=run, actor_id="worker")


def _scope(connection: Any) -> tuple[Any, ...]:
    return tuple(connection.execute("SELECT current_setting('app.tenant_id',true),current_setting('app.organization_id',true),current_setting('app.workspace_id',true),current_setting('app.legal_entity_id',true),current_setting('app.entity_id',true)").fetchone())


def test_live_raw_input_insert_seals_claimed_terminal_cancelled_and_requeued_states(seal_database: Any) -> None:
    import psycopg

    states = (("claimed", "Running", "Running", 1, False), ("failed", "Running", "Failed", 1, False), ("cancelled", "Running", "Cancelled", 0, True), ("requeued", "Running", "Queued", 1, False), ("cancel-pending", "Running", "Queued", 0, True))
    with seal_database["boundary"].transaction(TENANT) as connection:
        repository = PostgresReconciliationRepository(connection)
        assert tuple(connection.execute("SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user").fetchone()) == (False, False, False, False)
        _create(repository, "initial")
        _raw_insert(connection, "initial")
        for run, status, execution, attempt, cancelled in states:
            _create(repository, run)
            connection.execute("UPDATE reconforge.reconciliation_runs SET status=%s,execution_status=%s,execution_attempt=%s,cancel_requested=%s WHERE tenant_id=%s AND id=%s", (status, execution, attempt, cancelled, TENANT, run))
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="sealed"), connection.transaction():
                _raw_insert(connection, run)
            assert not repository.list_inputs(tenant_id=TENANT, run_id=run)
        completed = _completed(repository, "complete")
        before = repository.list_inputs(tenant_id=TENANT, run_id="complete")
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="sealed"), connection.transaction():
            _raw_insert(connection, "complete", "after-complete")
        repository.register_input(tenant_id=TENANT, run_id="complete", side="Left", source_id="source", record_hash="synthetic-fingerprint", amount="1", currency_code="USD")
        assert repository.list_inputs(tenant_id=TENANT, run_id="complete") == before
        assert completed["input_manifest_hash"] == repository._hash_payload(before)
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState), connection.transaction():
            connection.execute("UPDATE reconforge.reconciliation_runs SET status='Running',execution_status='Queued',execution_attempt=0 WHERE tenant_id=%s AND id='complete'", (TENANT,))


def test_live_raw_input_insert_requires_read_committed_without_scope_or_isolation_reset(seal_database: Any) -> None:
    import psycopg

    with seal_database["boundary"].transaction(TENANT) as connection:
        _create(PostgresReconciliationRepository(connection), "isolation")
    for isolation in ("REPEATABLE READ", "SERIALIZABLE", "READ UNCOMMITTED"):
        connection = seal_database["factory"].connect()
        try:
            with connection.transaction():
                connection.execute(psycopg.sql.SQL("SET TRANSACTION ISOLATION LEVEL {}").format(psycopg.sql.SQL(isolation)))
                set_local_tenant_scope(connection, TENANT)
                before = _scope(connection)
                with pytest.raises(psycopg.errors.InvalidTransactionState, match="READ COMMITTED"), connection.transaction():
                    _raw_insert(connection, "isolation")
                for table in ("results", "exceptions"):
                    with pytest.raises(psycopg.errors.InvalidTransactionState, match="READ COMMITTED"), connection.transaction():
                        _raw_output(connection, "isolation", table)
                assert _scope(connection) == before
                assert connection.execute("SHOW transaction_isolation").fetchone()[0] == isolation.lower()
        finally:
            connection.close()
    with seal_database["boundary"].transaction("input-seal-sibling") as connection, pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.ObjectNotInPrerequisiteState)), connection.transaction():
        _raw_insert(connection, "isolation")
    with seal_database["boundary"].transaction(TENANT) as connection:
        assert not PostgresReconciliationRepository(connection).list_inputs(tenant_id=TENANT, run_id="isolation")


def test_live_raw_outputs_require_active_lifecycle_and_preserve_completed_manifest(seal_database: Any) -> None:
    import psycopg

    states = (("initial", "Queued", 0, False, True), ("claimed", "Running", 1, False, True), ("requeued", "Queued", 1, False, False), ("failed", "Failed", 1, False, False), ("cancelled", "Cancelled", 1, True, False), ("cancel-pending", "Running", 1, True, False))
    with seal_database["boundary"].transaction(TENANT) as connection:
        repository = PostgresReconciliationRepository(connection)
        for label, execution, attempt, cancelled, allowed in states:
            run = "outputs-" + label
            _create(repository, run)
            connection.execute("UPDATE reconforge.reconciliation_runs SET execution_status=%s,execution_attempt=%s,cancel_requested=%s WHERE tenant_id=%s AND id=%s", (execution, attempt, cancelled, TENANT, run))
            for table in ("results", "exceptions"):
                if allowed:
                    _raw_output(connection, run, table)
                else:
                    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="sealed"), connection.transaction():
                        _raw_output(connection, run, table)
        completed = _completed(repository, "outputs-complete")
        before = repository.list_results(tenant_id=TENANT, run_id="outputs-complete")
        for table in ("results", "exceptions"):
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="sealed"), connection.transaction():
                _raw_output(connection, "outputs-complete", table)
        assert repository.list_results(tenant_id=TENANT, run_id="outputs-complete") == before
        assert not repository.list_exceptions(tenant_id=TENANT, run_id="outputs-complete")
        assert completed["result_set_hash"] == repository._hash_payload(before)


def test_live_claimed_input_updates_and_deletes_are_sealed_and_child_reparent_is_denied(seal_database: Any) -> None:
    import psycopg
    from psycopg import sql

    with seal_database["boundary"].transaction(TENANT) as connection:
        repository = PostgresReconciliationRepository(connection)
        _create(repository, "mutation")
        _create(repository, "destination")
        _raw_insert(connection, "mutation")
        _raw_output(connection, "mutation", "results")
        _raw_output(connection, "mutation", "exceptions")
        for table in ("inputs", "results", "exceptions"):
            for key, target in (("run_id", "destination"), ("tenant_id", "input-seal-sibling")):
                with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="identity"), connection.transaction():
                    connection.execute(sql.SQL("UPDATE {} SET {}=%s WHERE tenant_id=%s AND run_id='mutation'").format(sql.Identifier("reconforge", "reconciliation_" + table), sql.Identifier(key)), (target, TENANT))
        # Initial queued input corrections are still possible before a claim.
        assert connection.execute("UPDATE reconforge.reconciliation_inputs SET amount_original='1.00' WHERE tenant_id=%s AND run_id='mutation'", (TENANT,)).rowcount == 1
        repository.claim_run(tenant_id=TENANT, run_id="mutation", worker_id="worker")
        for statement in ("UPDATE reconforge.reconciliation_inputs SET amount_decimal=2 WHERE tenant_id=%s AND run_id='mutation'", "DELETE FROM reconforge.reconciliation_inputs WHERE tenant_id=%s AND run_id='mutation'"):
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="sealed"), connection.transaction():
                connection.execute(statement, (TENANT,))
        assert str(repository.list_inputs(tenant_id=TENANT, run_id="mutation")[0]["amount_decimal"]) == "1.000000000000000000"
        # Existing active-worker output corrections remain within the run.
        assert connection.execute("UPDATE reconforge.reconciliation_results SET explanation='Synthetic active correction' WHERE tenant_id=%s AND run_id='mutation'", (TENANT,)).rowcount == 1
        _completed(repository, "immutable-source")
        for table in ("inputs", "results"):
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState), connection.transaction():
                connection.execute(sql.SQL("UPDATE {} SET run_id='destination' WHERE tenant_id=%s AND run_id='immutable-source'").format(sql.Identifier("reconforge", "reconciliation_" + table)), (TENANT,))
        _create(repository, "editable-delete")
        _raw_insert(connection, "editable-delete")
        assert connection.execute("DELETE FROM reconforge.reconciliation_inputs WHERE tenant_id=%s AND run_id='editable-delete'", (TENANT,)).rowcount == 1


def test_input_seal_migration_matches_current_installer_and_preserves_history() -> None:
    from reconforge.infrastructure.postgres_reconciliation_input_seal import (
        POSTGRES_RECONCILIATION_INPUT_SEAL_SCHEMA_SQL,
    )

    path = Path("alembic/versions/0097_postgres_reconciliation_input_seal.py")
    spec = importlib.util.spec_from_file_location("input_seal_revision", path)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    assert revision.UPGRADE_SQL == POSTGRES_RECONCILIATION_INPUT_SEAL_SCHEMA_SQL
    assert revision.down_revision == "0096_pg_master_authority"
    assert "UPDATE reconforge.reconciliation_inputs" not in revision.UPGRADE_SQL
    assert "set_config" not in revision.UPGRADE_SQL and "SECURITY DEFINER" not in revision.UPGRADE_SQL


def test_live_raw_insert_serializes_with_claim_in_both_orders(seal_database: Any) -> None:
    import psycopg

    boundary = seal_database["boundary"]
    for insert_first in (True, False):
        run = "insert-first" if insert_first else "claim-first"
        with boundary.transaction(TENANT) as connection:
            _create(PostgresReconciliationRepository(connection), run)
        backend: Queue[int] = Queue()

        def contender(selected_run: str, selected_first: bool, selected_backend: Queue[int]) -> str:
            try:
                with boundary.transaction(TENANT) as other:
                    selected_backend.put(other.execute("SELECT pg_backend_pid()").fetchone()[0])
                    if selected_first:
                        PostgresReconciliationRepository(other).claim_run(tenant_id=TENANT, run_id=selected_run, worker_id="worker")
                    else:
                        _raw_insert(other, selected_run)
                return "committed"
            except psycopg.errors.ObjectNotInPrerequisiteState as exc:
                assert "sealed" in str(exc)
                return "denied"

        with ThreadPoolExecutor(max_workers=1) as pool:
            with boundary.transaction(TENANT) as connection:
                if insert_first:
                    _raw_insert(connection, run)
                else:
                    PostgresReconciliationRepository(connection).claim_run(tenant_id=TENANT, run_id=run, worker_id="worker")
                future = pool.submit(contender, run, insert_first, backend)
                pid = backend.get(timeout=5)
                with psycopg.connect(seal_database["admin"], autocommit=True) as observer:
                    deadline = monotonic() + 5
                    while monotonic() < deadline:
                        waiting = observer.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", (pid,)).fetchone()
                        if waiting and waiting[0] == "Lock":
                            break
                        assert not future.done(), "The competing operation bypassed the parent row lock"
                        sleep(0.01)
                    else:
                        pytest.fail("The competing operation did not wait on the run row")
            assert future.result(timeout=5) == ("committed" if insert_first else "denied")
        with boundary.transaction(TENANT) as connection:
            repository = PostgresReconciliationRepository(connection)
            assert len(repository.list_inputs(tenant_id=TENANT, run_id=run)) == int(insert_first)
            assert repository.get_run(tenant_id=TENANT, run_id=run)["execution_status"] == "Running"


def test_live_raw_outputs_serialize_with_completion_in_both_orders(seal_database: Any) -> None:
    import psycopg

    boundary = seal_database["boundary"]
    for table in ("results", "exceptions"):
        for insert_first in (True, False):
            run = f"complete-{table}-{'insert-first' if insert_first else 'complete-first'}"
            with boundary.transaction(TENANT) as connection:
                repository = PostgresReconciliationRepository(connection)
                _create(repository, run)
                repository.register_input(tenant_id=TENANT, run_id=run, side="Left", source_id="source", record_hash="synthetic", amount="1", currency_code="USD", allowed_uses=2)
                repository.append_result(tenant_id=TENANT, run_id=run, left_id="source", match_type="unmatched_left", confidence="0", explanation="Synthetic original result", status="Unmatched")
            backend: Queue[int] = Queue()

            def contender(selected_run: str, selected_table: str, selected_first: bool, selected_backend: Queue[int]) -> str:
                try:
                    with boundary.transaction(TENANT) as other:
                        selected_backend.put(other.execute("SELECT pg_backend_pid()").fetchone()[0])
                        if selected_first:
                            PostgresReconciliationRepository(other).complete_run(tenant_id=TENANT, run_id=selected_run, actor_id="worker")
                        else:
                            _raw_output(other, selected_run, selected_table)
                    return "committed"
                except psycopg.errors.ObjectNotInPrerequisiteState as exc:
                    assert "sealed" in str(exc)
                    return "denied"

            with ThreadPoolExecutor(max_workers=1) as pool:
                with boundary.transaction(TENANT) as connection:
                    if insert_first:
                        _raw_output(connection, run, table)
                    else:
                        PostgresReconciliationRepository(connection).complete_run(tenant_id=TENANT, run_id=run, actor_id="worker")
                    future = pool.submit(contender, run, table, insert_first, backend)
                    pid = backend.get(timeout=5)
                    with psycopg.connect(seal_database["admin"], autocommit=True) as observer:
                        deadline = monotonic() + 5
                        while monotonic() < deadline:
                            waiting = observer.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", (pid,)).fetchone()
                            if waiting and waiting[0] == "Lock":
                                break
                            assert not future.done(), "Output/completion bypassed the parent row lock"
                            sleep(0.01)
                        else:
                            pytest.fail("Output/completion did not wait on the parent run")
                assert future.result(timeout=5) == ("committed" if insert_first else "denied")
            with boundary.transaction(TENANT) as connection:
                repository = PostgresReconciliationRepository(connection)
                completed = repository.get_run(tenant_id=TENANT, run_id=run)
                results = repository.list_results(tenant_id=TENANT, run_id=run)
                assert completed["status"] == "Complete"
                assert completed["result_count"] == 1 + int(insert_first and table == "results")
                assert completed["exception_count"] == int(insert_first and table == "exceptions")
                assert completed["result_set_hash"] == repository._hash_payload(results)


def test_live_input_seal_upgrade_preserves_legacy_rows_without_repair_and_downgrades(seal_database: Any) -> None:
    import psycopg

    from alembic import command

    db = seal_database
    command.downgrade(db["config"], "0096_pg_master_authority")
    with db["boundary"].transaction(TENANT) as connection:
        repository = PostgresReconciliationRepository(connection)
        completed = _completed(repository, "legacy")
        _raw_insert(connection, "legacy", "historical-extra")
        before = repository.list_inputs(tenant_id=TENANT, run_id="legacy")
        assert completed["input_manifest_hash"] != repository._hash_payload(before)
    command.upgrade(db["config"], "0097_pg_reconciliation_seal")
    with db["boundary"].transaction(TENANT) as connection:
        repository = PostgresReconciliationRepository(connection)
        assert repository.list_inputs(tenant_id=TENANT, run_id="legacy") == before
        assert repository.get_run(tenant_id=TENANT, run_id="legacy")["input_manifest_hash"] == completed["input_manifest_hash"]
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="sealed"), connection.transaction():
            _raw_insert(connection, "legacy", "after-upgrade")
    command.downgrade(db["config"], "0096_pg_master_authority")
    with db["boundary"].transaction(TENANT) as connection:
        _raw_insert(connection, "legacy", "rollback-control")
    command.upgrade(db["config"], "0097_pg_reconciliation_seal")
    with db["boundary"].transaction(TENANT) as connection, pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="sealed"), connection.transaction():
        _raw_insert(connection, "legacy", "after-reupgrade")


def test_live_current_reconciliation_installer_applies_input_seal(seal_database: Any) -> None:
    import psycopg

    from alembic import command
    from reconforge.infrastructure.postgres_reconciliation import install_postgres_reconciliation_schema

    db = seal_database
    command.downgrade(db["config"], "0096_pg_master_authority")
    with psycopg.connect(db["admin"]) as admin:
        install_postgres_reconciliation_schema(admin)
        install_postgres_reconciliation_schema(admin)
        assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0096_pg_master_authority"
    with db["boundary"].transaction(TENANT) as connection:
        _completed(PostgresReconciliationRepository(connection), "installed")
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="sealed"), connection.transaction():
            _raw_insert(connection, "installed", "after-install")
