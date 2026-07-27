from __future__ import annotations

from pathlib import Path

import pytest

from reconforge.audit import AuditLedgerError, list_audit_events, verify_audit_events
from reconforge.auth import LocalAuthService
from reconforge.db import connect, database_status, run_migrations
from reconforge.db.migrations import MIGRATIONS
from reconforge.platform.common import ServerPrincipal, server_principal_context, trusted_local_mode
from reconforge.workflow import WorkflowService, WorkflowServiceError


def test_workflow_api_sessions_and_bridge_migrations_are_applied_and_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "workflow.db"

    first = run_migrations(db_path)
    second = run_migrations(db_path)
    status = database_status(db_path)

    latest = MIGRATIONS[-1].version
    assert first.applied_versions == list(range(1, latest + 1))
    assert first.current_version == latest
    assert second.applied_versions == []
    assert status.current_version == latest
    assert status.pending_versions == []

    connection = connect(db_path, require_exists=True)
    try:
        object_columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(workflow_objects)").fetchall()
        }
        transition_columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(workflow_transitions)").fetchall()
        }
        events_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'workflow_transition_events'",
        ).fetchone()
        sessions_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'api_sessions'",
        ).fetchone()
        bridge_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'legacy_import_records'",
        ).fetchone()
    finally:
        connection.close()

    assert {"id", "object_type", "object_id", "status", "created_at", "updated_at"} <= object_columns
    assert {"reason_required", "active"} <= transition_columns
    assert events_table is not None
    assert sessions_table is not None
    assert bridge_table is not None


def test_builtin_workflow_transitions_exist(tmp_path: Path) -> None:
    db_path = tmp_path / "templates.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = WorkflowService(connection)
        object_types = {
            str(row["object_type"])
            for row in connection.execute("SELECT DISTINCT object_type FROM workflow_transitions").fetchall()
        }
        reconciliation = service.list_allowed_transitions(object_type="reconciliation")
    finally:
        connection.close()

    assert {"generic_review", "reconciliation", "close_task", "control_test", "evidence_requirement"} <= object_types
    assert any(
        transition.from_status == "Draft"
        and transition.to_status == "Prepared"
        and transition.required_permission == "reconciliation.prepare"
        for transition in reconciliation
    )


def test_workflow_object_can_be_initialized_and_transitioned(tmp_path: Path) -> None:
    db_path = tmp_path / "transition.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = WorkflowService(connection)
        created = service.initialize_object(object_type="reconciliation", object_id="REC-001", status="Draft")
        updated = service.perform_transition(
            object_type="reconciliation",
            object_id="REC-001",
            to_status="Prepared",
            reason="Prepared for review",
        )
        current = service.get_status(object_type="reconciliation", object_id="REC-001")
    finally:
        connection.close()

    assert created.status == "Draft"
    assert updated.status == "Prepared"
    assert current.status == "Prepared"


def test_workflow_transition_rejects_actor_mismatch_under_server_principal(tmp_path: Path) -> None:
    db_path = tmp_path / "principal-mismatch.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        auth = LocalAuthService(connection)
        user = auth.create_user(username="preparer", password="Secret-123", role="preparer")
        principal = ServerPrincipal(user=user, permissions=frozenset({"reconciliation.prepare"}))
        service = WorkflowService(connection)
        service.initialize_object(object_type="reconciliation", object_id="REC-PRINCIPAL", status="Draft")

        with trusted_local_mode(False), server_principal_context(principal):
            with pytest.raises(
                WorkflowServiceError, match="Authenticated actor label must match the current server principal."
            ):
                service.perform_transition(
                    object_type="reconciliation",
                    object_id="REC-PRINCIPAL",
                    to_status="Prepared",
                    actor_label="local-cli",
                    reason="Prepared for review",
                )

            updated = service.perform_transition(
                object_type="reconciliation",
                object_id="REC-PRINCIPAL",
                to_status="Prepared",
                actor_label="preparer",
                reason="Prepared for review",
            )
    finally:
        connection.close()

    assert updated.status == "Prepared"


def test_workflow_transaction_boundary_can_be_rolled_back_by_application_service(tmp_path: Path) -> None:
    db_path = tmp_path / "transaction_boundary.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        audit_count = connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"]
        service = WorkflowService(connection, autocommit=False)
        service.initialize_object(object_type="reconciliation", object_id="REC-TRANSACTION", status="Draft")
        updated = service.perform_transition(
            object_type="reconciliation",
            object_id="REC-TRANSACTION",
            to_status="Prepared",
            actor_label="local-cli",
            reason="Prepared inside caller transaction",
        )
        assert updated.status == "Prepared"
        assert connection.in_transaction
        connection.rollback()

        workflow_object = connection.execute(
            "SELECT 1 FROM workflow_objects WHERE object_type = 'reconciliation' AND object_id = 'REC-TRANSACTION'",
        ).fetchone()
        transition_event = connection.execute(
            """
            SELECT 1
            FROM workflow_transition_events AS event
            JOIN workflow_objects AS object ON object.id = event.workflow_object_id
            WHERE object.object_type = 'reconciliation' AND object.object_id = 'REC-TRANSACTION'
            """,
        ).fetchone()
        assert workflow_object is None
        assert transition_event is None
        assert connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"] == audit_count
    finally:
        connection.close()


def test_workflow_transition_rolls_back_when_audit_write_fails(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "audit_failure_boundary.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = WorkflowService(connection)
        service.initialize_object(object_type="reconciliation", object_id="REC-FAILED", status="Draft")
        audit_count = connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"]

        def _forced_audit_failure(*_: object, **__: object) -> None:
            raise AuditLedgerError("forced audit failure")

        monkeypatch.setattr("reconforge.platform.common.append_audit_event", _forced_audit_failure)
        with pytest.raises(WorkflowServiceError, match="Unable to persist workflow transition with audit evidence"):
            service.perform_transition(
                object_type="reconciliation",
                object_id="REC-FAILED",
                to_status="Prepared",
                actor_label="local-cli",
                reason="Prepared for review",
            )

        workflow_state = connection.execute(
            "SELECT status FROM workflow_objects WHERE object_type = 'reconciliation' AND object_id = 'REC-FAILED'"
        ).fetchone()
        transition_events = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM workflow_transition_events AS event
            JOIN workflow_objects AS object ON object.id = event.workflow_object_id
            WHERE object.object_type = 'reconciliation' AND object.object_id = 'REC-FAILED'
            """
        ).fetchone()
        assert workflow_state is not None
        assert workflow_state["status"] == "Draft"
        assert transition_events["count"] == 0
        assert connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"] == audit_count
    finally:
        connection.close()


def test_invalid_workflow_transition_fails_safely(tmp_path: Path) -> None:
    db_path = tmp_path / "invalid.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = WorkflowService(connection)
        service.initialize_object(object_type="reconciliation", object_id="REC-001", status="Draft")
        with pytest.raises(WorkflowServiceError, match="Invalid workflow transition"):
            service.perform_transition(
                object_type="reconciliation",
                object_id="REC-001",
                to_status="Reviewed",
            )
    finally:
        connection.close()


def test_transition_requiring_reason_rejects_empty_reason(tmp_path: Path) -> None:
    db_path = tmp_path / "reason.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = WorkflowService(connection)
        service.initialize_object(object_type="reconciliation", object_id="REC-001", status="Draft")
        with pytest.raises(WorkflowServiceError, match="requires a reason"):
            service.perform_transition(
                object_type="reconciliation",
                object_id="REC-001",
                to_status="Not Applicable",
            )
    finally:
        connection.close()


def test_required_permission_is_checked_when_actor_user_exists(tmp_path: Path) -> None:
    db_path = tmp_path / "permission.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        auth = LocalAuthService(connection)
        auth.create_user(username="reviewer", password="Secret-123", role="reviewer")
        auth.create_user(username="preparer", password="Secret-123", role="preparer")
        service = WorkflowService(connection)
        service.initialize_object(object_type="reconciliation", object_id="REC-001", status="Draft")

        with pytest.raises(WorkflowServiceError, match="required permission"):
            service.perform_transition(
                object_type="reconciliation",
                object_id="REC-001",
                to_status="Prepared",
                actor_label="reviewer",
            )

        updated = service.perform_transition(
            object_type="reconciliation",
            object_id="REC-001",
            to_status="Prepared",
            actor_label="preparer",
        )
    finally:
        connection.close()

    assert updated.status == "Prepared"


def test_sod_conflict_is_detected_for_prepare_review(tmp_path: Path) -> None:
    db_path = tmp_path / "sod.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        auth = LocalAuthService(connection)
        auth.create_user(username="controller", password="Secret-123", role="controller")
        service = WorkflowService(connection)
        service.initialize_object(object_type="reconciliation", object_id="REC-001", status="Draft")
        service.perform_transition(
            object_type="reconciliation",
            object_id="REC-001",
            to_status="Prepared",
            actor_label="controller",
        )
        service.perform_transition(
            object_type="reconciliation",
            object_id="REC-001",
            to_status="In Review",
            actor_label="controller",
        )

        with pytest.raises(WorkflowServiceError, match="Separation of duties"):
            service.perform_transition(
                object_type="reconciliation",
                object_id="REC-001",
                to_status="Reviewed",
                actor_label="controller",
            )
    finally:
        connection.close()


def test_trusted_local_label_cannot_bypass_workflow_sod(tmp_path: Path) -> None:
    db_path = tmp_path / "trusted-local-sod.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = WorkflowService(connection)
        service.initialize_object(object_type="reconciliation", object_id="REC-LOCAL-SOD", status="Draft")
        service.perform_transition(
            object_type="reconciliation",
            object_id="REC-LOCAL-SOD",
            to_status="Prepared",
            actor_label="Local-Operator",
        )
        service.perform_transition(
            object_type="reconciliation",
            object_id="REC-LOCAL-SOD",
            to_status="In Review",
            actor_label="local-operator",
        )

        with pytest.raises(WorkflowServiceError, match="Separation of duties"):
            service.perform_transition(
                object_type="reconciliation",
                object_id="REC-LOCAL-SOD",
                to_status="Reviewed",
                actor_label=" LOCAL-OPERATOR ",
            )
    finally:
        connection.close()


def test_successful_transition_writes_audit_event_and_chain_verifies(tmp_path: Path) -> None:
    db_path = tmp_path / "audit_workflow.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = WorkflowService(connection)
        service.initialize_object(object_type="reconciliation", object_id="REC-001", status="Draft")
        service.perform_transition(
            object_type="reconciliation",
            object_id="REC-001",
            to_status="Prepared",
            actor_label="local-cli",
            reason="Prepared for review",
        )
        events = list_audit_events(connection)
        verification = verify_audit_events(connection)
        history = service.list_history(object_type="reconciliation", object_id="REC-001")
    finally:
        connection.close()

    assert verification.ok
    assert any(event.action == "workflow_transition" for event in events)
    workflow_event = next(event for event in events if event.action == "workflow_transition")
    assert workflow_event.metadata["from_status"] == "Draft"
    assert workflow_event.metadata["to_status"] == "Prepared"
    assert workflow_event.metadata["reason"] == "Prepared for review"
    assert len(history) == 1
    assert history[0].actor_label == "local-cli"
