from __future__ import annotations

from pathlib import Path

import pytest

from reconforge.audit import list_audit_events, verify_audit_events
from reconforge.auth import LocalAuthService
from reconforge.db import connect, database_status, run_migrations
from reconforge.workflow import WorkflowService, WorkflowServiceError


def test_workflow_migration_v3_is_applied_and_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "workflow.db"

    first = run_migrations(db_path)
    second = run_migrations(db_path)
    status = database_status(db_path)

    assert first.applied_versions == [1, 2, 3]
    assert first.current_version == 3
    assert second.applied_versions == []
    assert status.current_version == 3
    assert status.pending_versions == []

    connection = connect(db_path, require_exists=True)
    try:
        object_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(workflow_objects)").fetchall()
        }
        transition_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(workflow_transitions)").fetchall()
        }
        events_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'workflow_transition_events'",
        ).fetchone()
    finally:
        connection.close()

    assert {"id", "object_type", "object_id", "status", "created_at", "updated_at"} <= object_columns
    assert {"reason_required", "active"} <= transition_columns
    assert events_table is not None


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
