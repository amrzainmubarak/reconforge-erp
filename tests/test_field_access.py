from reconforge.auth.field_access import (
    REDACTED_VALUE,
    project_account_reconciliation,
    project_audit_event,
    project_close_period,
    project_close_readiness,
    project_close_task,
    project_consolidation_period,
    project_consolidation_run,
    project_evidence_drill_down_record,
    project_evidence_requirement,
    project_evidence_verification,
    project_exception,
    project_fields,
    project_finance_entry,
    project_reconciliation_exception,
    project_reconciliation_input,
    project_reconciliation_result,
    project_reconciliation_run,
)
from reconforge.auth.policy import CentralPolicyEngine, PolicyEvaluationContext


def test_field_projection_masks_and_denies_without_leaking_values() -> None:
    result = project_fields(
        {"account": "1000", "amount": "123.45", "secret": "do-not-leak"},
        allowed_fields=frozenset({"account", "amount"}),
        masked_fields=frozenset({"amount"}),
    )
    assert result.visible == {"account": "1000", "amount": REDACTED_VALUE}
    assert result.masked_fields == ("amount",)
    assert result.denied_fields == ("secret",)
    assert "do-not-leak" not in str(result.visible)


def test_field_projection_is_permutation_stable_and_masking_is_not_authorization() -> None:
    first = project_fields({"b": 2, "a": 1}, allowed_fields=frozenset({"a", "b"}))
    second = project_fields({"a": 1, "b": 2}, allowed_fields=frozenset({"a", "b"}))
    assert first.projection_digest == second.projection_digest
    denied = CentralPolicyEngine().evaluate(
        PolicyEvaluationContext(
            user_id="u1",
            username="u1",
            user_permissions={"finance.read"},
            requested_field_names=frozenset({"secret"}),
            authorized_field_names=frozenset({"amount"}),
        ),
        required_permission="finance.read",
    )
    assert denied.reason_code == "field_scope_denied"


def test_evidence_projection_is_allowlisted_in_both_modes_and_projects_links() -> None:
    record = {
        "id": "evidence-1",
        "evidence_code": "CLOSE-1",
        "source_path": "/sensitive/path.pdf",
        "checksum_sha256": "a" * 64,
        "unknown_future_column": "must-not-escape",
        "links": [
            {
                "id": "link-1",
                "object_type": "close_task",
                "object_id": "task-1",
                "link_type": "support",
                "unknown_link_column": "must-not-escape",
            }
        ],
    }

    redacted = project_evidence_drill_down_record(record, include_sensitive=False)
    assert redacted.visible["source_path"] == "***redacted***"
    assert redacted.visible["checksum_sha256"] == "***redacted***"
    assert redacted.denied_fields == ("unknown_future_column",)
    assert redacted.visible["links"] == [
        {"id": "link-1", "link_type": "support", "object_id": "task-1", "object_type": "close_task"}
    ]
    assert "must-not-escape" not in str(redacted.visible)

    sensitive = project_evidence_drill_down_record(record, include_sensitive=True)
    assert sensitive.visible["source_path"] == "/sensitive/path.pdf"
    assert sensitive.visible["checksum_sha256"] == "a" * 64
    assert sensitive.denied_fields == ("unknown_future_column",)
    assert sensitive.projection_digest != redacted.projection_digest


def test_legacy_audit_projection_masks_sensitive_aliases_and_denies_future_fields() -> None:
    result = project_audit_event(
        {
            "event_id": "event-1",
            "actor_id": "user-1",
            "resource_id": "record-1",
            "metadata": {"secret": "must-not-leak"},
            "action": "ledger.read",
            "unknown_future_column": "must-not-escape",
        }
    )
    assert result.visible == {
        "action": "ledger.read",
        "actor_id": REDACTED_VALUE,
        "event_id": "event-1",
        "metadata": REDACTED_VALUE,
        "resource_id": REDACTED_VALUE,
    }
    assert result.denied_fields == ("unknown_future_column",)
    assert "must-not-leak" not in str(result.visible)
    assert result.projection_digest == project_audit_event(
        {
            "resource_id": "record-1",
            "metadata": {"another": "secret"},
            "actor_id": "user-2",
            "event_id": "event-1",
            "action": "ledger.read",
            "unknown_future_column": "different-value",
        }
    ).projection_digest


def test_evidence_mutation_projections_drop_unknown_adapter_fields() -> None:
    requirement = project_evidence_requirement(
        {
            "id": "requirement-1",
            "object_type": "close_task",
            "object_id": "task-1",
            "requirement_code": "TB",
            "description": "Trial balance support",
            "required_status": "Required",
            "unknown_future_column": "must-not-escape",
        }
    )
    verification = project_evidence_verification(
        {
            "evidence_id": "evidence-1",
            "ok": True,
            "expected_sha256": "a" * 64,
            "actual_sha256": "a" * 64,
            "unknown_future_column": "must-not-escape",
        }
    )
    assert "unknown_future_column" not in requirement.visible
    assert requirement.denied_fields == ("unknown_future_column",)
    assert "unknown_future_column" not in verification.visible
    assert verification.denied_fields == ("unknown_future_column",)


def test_finance_entry_projection_is_closed_across_local_and_server_shapes() -> None:
    result = project_finance_entry(
        {
            "tenant_id": "tenant-a",
            "id": "GLE-1",
            "entry_number": "JE-001",
            "currency_code": "USD",
            "total_debit_minor": 1000,
            "total_credit_minor": 1000,
            "source_id": "import-1",
            "entry_fingerprint": "fingerprint",
            "unknown_future_column": "must-not-escape",
            "lines": [
                {
                    "id": "line-1",
                    "entry_id": "GLE-1",
                    "line_number": 1,
                    "account_id": "account-1",
                    "credit_amount": "0",
                    "debit_amount": "10.00",
                    "unknown_line_column": "must-not-escape",
                }
            ],
        }
    )
    assert result.visible["entry_number"] == "JE-001"
    assert result.visible["lines"] == [
        {
            "account_id": "account-1",
            "credit_amount": "0",
            "debit_amount": "10.00",
            "entry_id": "GLE-1",
            "id": "line-1",
            "line_number": 1,
        }
    ]
    assert result.denied_fields == ("unknown_future_column",)
    assert "unknown_line_column" not in str(result.visible)


def test_close_projections_drop_unknown_adapter_fields_across_record_shapes() -> None:
    period = project_close_period(
        {
            "id": "period-1",
            "workspace_id": "default",
            "period_name": "2026-08",
            "status": "Open",
            "unknown_future_column": "must-not-escape",
        }
    )
    task = project_close_task(
        {
            "id": "task-1",
            "close_period_id": "period-1",
            "task_code": "CLOSE-001",
            "name": "Review",
            "unknown_future_column": "must-not-escape",
        }
    )
    readiness = project_close_readiness(
        {
            "period_id": "period-1",
            "period_name": "2026-08",
            "total_tasks": 1,
            "complete_tasks": 1,
            "blocked_tasks": 0,
            "readiness_score": "100.00",
            "unknown_future_column": "must-not-escape",
        }
    )
    assert period.visible["period_name"] == "2026-08"
    assert task.visible["task_code"] == "CLOSE-001"
    assert readiness.visible["readiness_score"] == "100.00"
    assert period.denied_fields == task.denied_fields == readiness.denied_fields == ("unknown_future_column",)
    assert "must-not-escape" not in str(period.visible | task.visible | readiness.visible)


def test_exception_projection_drops_unknown_adapter_fields() -> None:
    result = project_exception(
        {
            "id": "exception-1",
            "workspace_id": "default",
            "source_type": "reconciliation",
            "source_id": "recon-1",
            "status": "Open",
            "description": "Synthetic exception",
            "unknown_future_column": "must-not-escape",
        }
    )
    assert result.visible["source_id"] == "recon-1"
    assert result.denied_fields == ("unknown_future_column",)
    assert "must-not-escape" not in str(result.visible)


def test_account_reconciliation_projection_drops_unknown_storage_and_item_fields() -> None:
    result = project_account_reconciliation(
        {
            "id": "rec-1",
            "status": "Draft",
            "balance_decimal": "10.00",
            "items": [
                {
                    "id": "item-1",
                    "amount_decimal": "10.00",
                    "unknown_future_item_column": "must-not-escape",
                }
            ],
            "unknown_future_record_column": "must-not-escape",
        }
    )
    assert result.visible["balance_decimal"] == "10.00"
    assert result.visible["items"] == [{"amount_decimal": "10.00", "id": "item-1"}]
    assert result.denied_fields == ("unknown_future_record_column",)
    assert "must-not-escape" not in str(result.visible)


def test_reconciliation_projection_drops_unknown_run_and_child_fields() -> None:
    run = project_reconciliation_run(
        {
            "id": "run-1",
            "status": "Complete",
            "inputs": [{"source_id": "bank-1", "unknown_future_input_column": "must-not-escape"}],
            "results": [{"id": "match-1", "unknown_future_result_column": "must-not-escape"}],
            "unknown_future_run_column": "must-not-escape",
        }
    )
    assert run.visible["inputs"] == [{"source_id": "bank-1"}]
    assert run.visible["results"] == [{"id": "match-1"}]
    assert run.denied_fields == ("unknown_future_run_column",)
    assert project_reconciliation_input({"source_id": "bank-1", "future": "x"}).denied_fields == ("future",)
    assert project_reconciliation_result({"id": "match-1", "future": "x"}).denied_fields == ("future",)
    assert project_reconciliation_exception({"id": "exception-1", "future": "x"}).denied_fields == ("future",)
    assert "must-not-escape" not in str(run.visible)


def test_consolidation_projection_drops_unknown_storage_and_child_fields() -> None:
    period = project_consolidation_period(
        {
            "id": "period-1",
            "workspace_id": "default",
            "group_code": "GLOBAL",
            "period_name": "2026-08",
            "unknown_future_column": "must-not-escape",
        }
    )
    run = project_consolidation_run(
        {
            "id": "run-1",
            "period_id": "period-1",
            "status": "Prepared",
            "journal_lines": [
                {
                    "id": "line-1",
                    "ordinal": 1,
                    "amount_minor": 100,
                    "unknown_future_line_column": "must-not-escape",
                }
            ],
            "effects": [
                {
                    "id": "effect-1",
                    "effect_type": "Posting",
                    "lines": [
                        {
                            "id": "effect-line-1",
                            "amount_minor": -100,
                            "unknown_future_effect_line_column": "must-not-escape",
                        }
                    ],
                    "unknown_future_effect_column": "must-not-escape",
                }
            ],
            "unknown_future_run_column": "must-not-escape",
        }
    )
    assert period.visible["period_name"] == "2026-08"
    assert run.visible["journal_lines"] == [{"amount_minor": 100, "id": "line-1", "ordinal": 1}]
    assert run.visible["effects"] == [
        {
            "id": "effect-1",
            "effect_type": "Posting",
            "lines": [{"amount_minor": -100, "id": "effect-line-1"}],
        }
    ]
    assert period.denied_fields == ("unknown_future_column",)
    assert run.denied_fields == ("unknown_future_run_column",)
    assert "must-not-escape" not in str(period.visible | run.visible)
