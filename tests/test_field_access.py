from reconforge.auth.field_access import (
    REDACTED_VALUE,
    project_account_reconciliation,
    project_audit_event,
    project_auth_me,
    project_bank_statement,
    project_close_period,
    project_close_readiness,
    project_close_task,
    project_consolidation_ownership_effective_response,
    project_consolidation_ownership_interest_response,
    project_consolidation_period,
    project_consolidation_ppa_response,
    project_consolidation_run,
    project_consolidation_summary,
    project_evidence_drill_down_record,
    project_evidence_requirement,
    project_evidence_verification,
    project_exception,
    project_fields,
    project_finance_account,
    project_finance_chart,
    project_finance_dimension,
    project_finance_dimension_value,
    project_finance_entry,
    project_finance_journal,
    project_finance_summary,
    project_individual_cashflow,
    project_inventory_control_exceptions,
    project_inventory_core_snapshot,
    project_inventory_core_summary,
    project_inventory_cost_layer,
    project_inventory_item,
    project_inventory_location,
    project_inventory_lot,
    project_inventory_movement,
    project_inventory_on_hand,
    project_inventory_planning_session,
    project_inventory_planning_snapshot,
    project_inventory_planning_summary,
    project_inventory_reorder_rule,
    project_inventory_reorder_signals,
    project_inventory_uom,
    project_inventory_valuation_document,
    project_inventory_valuation_policy,
    project_inventory_valuation_reversal,
    project_inventory_valuation_reversal_snapshot,
    project_inventory_valuation_reversal_summary,
    project_inventory_valuation_snapshot,
    project_inventory_warehouse,
    project_manufacturing_cost_control,
    project_master_snapshot,
    project_master_summary,
    project_metric_dashboard,
    project_metric_lineage,
    project_payables_purchase_order,
    project_payables_receipt,
    project_payables_supplier,
    project_payables_supplier_invoice,
    project_payables_three_way_match,
    project_professional_invoice_payment,
    project_receivables_aging,
    project_receivables_credit_exposure,
    project_receivables_customer,
    project_receivables_invoice,
    project_receivables_receipt,
    project_reconciliation_exception,
    project_reconciliation_input,
    project_reconciliation_result,
    project_reconciliation_run,
    project_retail_settlement,
    project_scope_grant,
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


def test_finance_core_master_projections_are_closed() -> None:
    cases = (
        (project_finance_chart, {"id": "chart-1", "chart_code": "DEFAULT", "unknown": "must-not-escape"}),
        (project_finance_account, {"id": "account-1", "account_code": "1000", "unknown": "must-not-escape"}),
        (project_finance_dimension, {"id": "dimension-1", "dimension_code": "CC", "unknown": "must-not-escape"}),
        (
            project_finance_dimension_value,
            {"id": "value-1", "value_code": "HQ", "unknown": "must-not-escape"},
        ),
        (project_finance_journal, {"id": "journal-1", "journal_code": "GENERAL", "unknown": "must-not-escape"}),
    )

    for projector, record in cases:
        result = projector(record)
        assert result.visible == {key: value for key, value in record.items() if key != "unknown"}
        assert result.denied_fields == ("unknown",)
        assert "must-not-escape" not in str(result.visible)


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


def test_finance_summary_projection_is_closed_across_server_shapes() -> None:
    result = project_finance_summary(
        {
            "workspace": "workspace-a",
            "charts": 1,
            "accounts": 2,
            "dimensions": 3,
            "dimension_values": 4,
            "journals": 5,
            "draft_entries": 6,
            "validated_entries": 7,
            "voided_entries": 8,
            "source": {
                "kind": "postgres-ledger-control",
                "server_mode": True,
                "unknown_source_field": "must-not-escape",
            },
            "unsupported_collections": ["journals"],
            "unknown_summary_field": "must-not-escape",
        }
    )

    assert result.visible == {
        "workspace": "workspace-a",
        "charts": 1,
        "accounts": 2,
        "dimensions": 3,
        "dimension_values": 4,
        "journals": 5,
        "draft_entries": 6,
        "validated_entries": 7,
        "voided_entries": 8,
        "source": {"kind": "postgres-ledger-control", "server_mode": True},
        "unsupported_collections": ["journals"],
    }
    assert result.denied_fields == ("unknown_summary_field",)
    assert "unknown_source_field" not in str(result.visible)


def test_consolidation_summary_projection_is_closed() -> None:
    result = project_consolidation_summary(
        {
            "workspace": "workspace-a",
            "periods": 1,
            "locked_periods": 1,
            "prepared_runs": 2,
            "approved_runs": 3,
            "posted_runs": 4,
            "reversal_prepared_runs": 5,
            "reversed_runs": 6,
            "unknown_summary_field": "must-not-escape",
        }
    )

    assert result.visible == {
        "workspace": "workspace-a",
        "periods": 1,
        "locked_periods": 1,
        "prepared_runs": 2,
        "approved_runs": 3,
        "posted_runs": 4,
        "reversal_prepared_runs": 5,
        "reversed_runs": 6,
    }
    assert result.denied_fields == ("unknown_summary_field",)


def test_auth_me_projection_is_closed_across_identity_scopes() -> None:
    result = project_auth_me(
        {
            "id": "user-a",
            "username": "alice",
            "display_name": "Alice",
            "email": "alice@example.test",
            "disabled": False,
            "created_at": "2026-08-27T00:00:00Z",
            "roles": ["reviewer"],
            "principal_type": "user",
            "authorized_scopes": {
                "workspaces": ["workspace-a"],
                "organizations": ["org-a"],
                "legal_entities": ["entity-a"],
                "future_scope": ["must-not-escape"],
            },
            "future_identity_field": "must-not-escape",
        }
    )

    assert result.visible["authorized_scopes"] == {
        "workspaces": ["workspace-a"],
        "organizations": ["org-a"],
        "legal_entities": ["entity-a"],
    }
    assert "future_identity_field" in result.denied_fields
    assert "future_scope" not in str(result.visible["authorized_scopes"])


def test_scope_grant_projection_is_closed() -> None:
    result = project_scope_grant(
        {
            "id": "grant-a",
            "principal_type": "user",
            "principal_id": "user-a",
            "scope_type": "workspace",
            "scope_id": "workspace-a",
            "granted_by": "admin-a",
            "granted_at": "2026-08-27T00:00:00Z",
            "future_scope_grant_field": "must-not-escape",
        }
    )

    assert result.visible["scope_id"] == "workspace-a"
    assert result.denied_fields == ("future_scope_grant_field",)


def test_metric_projections_are_closed() -> None:
    dashboard = project_metric_dashboard(
        {
            "id": "metric-a",
            "workspace_id": "workspace-a",
            "metric_key": "match_rate",
            "period_name": "2026-08",
            "value": "100.00",
            "value_text": "100.00",
            "lineage": "reconciliation_results",
            "computed_at": "2026-08-27T00:00:00Z",
            "name": "Match rate",
            "description": "Matched results percentage",
            "future_metric_field": "must-not-escape",
        }
    )
    lineage = project_metric_lineage(
        {
            "metric_key": "match_rate",
            "name": "Match rate",
            "description": "Matched results percentage",
            "lineage": "reconciliation_results",
            "future_lineage_field": "must-not-escape",
        }
    )

    assert dashboard.visible["metric_key"] == "match_rate"
    assert dashboard.denied_fields == ("future_metric_field",)
    assert lineage.visible["lineage"] == "reconciliation_results"
    assert lineage.denied_fields == ("future_lineage_field",)


def test_inventory_valuation_document_projection_is_closed_across_nested_financial_shapes() -> None:
    result = project_inventory_valuation_document(
        {
            "id": "valuation-1",
            "valuation_number": "VAL-001",
            "total_value": "12.34",
            "unknown_document_column": "must-not-escape",
            "input_costs": [
                {
                    "id": "cost-1",
                    "line_number": 1,
                    "total_cost": "12.34",
                    "unknown_cost_column": "must-not-escape",
                }
            ],
            "lines": [
                {
                    "id": "line-1",
                    "line_number": 1,
                    "flow_direction": "Inbound",
                    "quantity": "1.000",
                    "value": "12.34",
                    "unknown_line_column": "must-not-escape",
                }
            ],
            "layer_consumptions": [
                {
                    "id": "consumption-1",
                    "cost_layer_id": "layer-1",
                    "quantity": "1.000",
                    "value": "12.34",
                    "unknown_consumption_column": "must-not-escape",
                }
            ],
        }
    )

    assert result.visible["valuation_number"] == "VAL-001"
    assert result.visible["input_costs"] == [{"id": "cost-1", "line_number": 1, "total_cost": "12.34"}]
    assert result.visible["lines"] == [
        {"flow_direction": "Inbound", "id": "line-1", "line_number": 1, "quantity": "1.000", "value": "12.34"}
    ]
    assert result.visible["layer_consumptions"] == [
        {"cost_layer_id": "layer-1", "id": "consumption-1", "quantity": "1.000", "value": "12.34"}
    ]
    assert result.denied_fields == ("unknown_document_column",)
    assert "must-not-escape" not in str(result.visible)


def test_inventory_valuation_policy_layer_and_snapshot_projection_is_closed() -> None:
    policy = project_inventory_valuation_policy(
        {"id": "policy-1", "policy_code": "FIFO", "active": True, "unknown": "must-not-escape"}
    )
    layer = project_inventory_cost_layer(
        {
            "id": "layer-1",
            "quantity_precision": 3,
            "original_quantity": "1.000",
            "remaining_quantity": "1.000",
            "original_value": "12.34",
            "remaining_value": "12.34",
            "layer_status": "Open",
            "unknown": "must-not-escape",
        }
    )
    snapshot = project_inventory_valuation_snapshot(
        {
            "schema_version": 1,
            "workspace": "default",
            "source": {"kind": "local-inventory-valuation", "unknown": "must-not-escape"},
            "summary": {"workspace": "default", "policies": 1, "unknown": "must-not-escape"},
            "policies": [{"policy_code": "FIFO", "unknown": "must-not-escape"}],
            "documents": [{"valuation_number": "VAL-001", "unknown": "must-not-escape"}],
            "open_cost_layers": [{"id": "layer-1", "unknown": "must-not-escape"}],
            "unknown": "must-not-escape",
        }
    )

    assert policy.visible == {"active": True, "id": "policy-1", "policy_code": "FIFO"}
    assert layer.visible["layer_status"] == "Open"
    assert snapshot.visible["policies"] == [{"policy_code": "FIFO"}]
    assert snapshot.visible["documents"] == [{"valuation_number": "VAL-001"}]
    assert snapshot.visible["open_cost_layers"] == [{"id": "layer-1"}]
    assert snapshot.denied_fields == ("unknown",)
    assert "must-not-escape" not in str(snapshot.visible)


def test_inventory_valuation_reversal_projection_is_closed_across_effects_and_snapshot() -> None:
    reversal = project_inventory_valuation_reversal(
        {
            "id": "reversal-1",
            "reversal_number": "REV-001",
            "total_value": "12.34",
            "effects": [
                {
                    "id": "effect-1",
                    "effect_type": "Restore",
                    "quantity": "1.000",
                    "value": "12.34",
                    "unknown_effect_field": "must-not-escape",
                }
            ],
            "unknown_reversal_field": "must-not-escape",
        }
    )
    summary = project_inventory_valuation_reversal_summary(
        {"workspace": "default", "approved_reversals": 1, "unknown": "must-not-escape"}
    )
    snapshot = project_inventory_valuation_reversal_snapshot(
        {
            "schema_version": 1,
            "workspace": "default",
            "source": {"kind": "local-inventory-valuation-reversal", "unknown": "must-not-escape"},
            "summary": {"workspace": "default", "approved_reversals": 1, "unknown": "must-not-escape"},
            "reversals": [{"reversal_number": "REV-001", "unknown": "must-not-escape"}],
            "unknown": "must-not-escape",
        }
    )

    assert reversal.visible["effects"] == [
        {"effect_type": "Restore", "id": "effect-1", "quantity": "1.000", "value": "12.34"}
    ]
    assert summary.visible == {"approved_reversals": 1, "workspace": "default"}
    assert snapshot.visible["reversals"] == [{"reversal_number": "REV-001"}]
    assert snapshot.denied_fields == ("unknown",)
    assert "must-not-escape" not in str(reversal.visible | snapshot.visible)


def test_inventory_core_master_projection_is_closed_for_each_resource() -> None:
    records = (
        project_inventory_uom({"id": "uom-1", "uom_code": "EA", "unknown": "must-not-escape"}),
        project_inventory_item({"id": "item-1", "item_code": "ITEM", "unknown": "must-not-escape"}),
        project_inventory_warehouse({"id": "warehouse-1", "warehouse_code": "MAIN", "unknown": "must-not-escape"}),
        project_inventory_location({"id": "location-1", "location_code": "STOCK", "unknown": "must-not-escape"}),
        project_inventory_lot({"id": "lot-1", "lot_serial_code": "LOT-1", "unknown": "must-not-escape"}),
    )

    assert [record.visible["id"] for record in records] == [
        "uom-1",
        "item-1",
        "warehouse-1",
        "location-1",
        "lot-1",
    ]
    assert all(record.denied_fields == ("unknown",) for record in records)
    assert "must-not-escape" not in str([record.visible for record in records])


def test_inventory_core_operational_projection_is_closed_recursively() -> None:
    movement = project_inventory_movement(
        {
            "id": "movement-1",
            "lines": [
                {
                    "id": "line-1",
                    "quantity_scaled": 1250,
                    "quantity": "1.250",
                    "unknown_line_field": "must-not-escape",
                }
            ],
            "unknown_movement_field": "must-not-escape",
        }
    )
    on_hand = project_inventory_on_hand(
        {
            "schema_version": 1,
            "source": {"kind": "local-inventory-ledger", "future_source_field": "must-not-escape"},
            "balances": [{"item_code": "ITEM", "quantity_scaled": 2, "unknown_balance_field": "must-not-escape"}],
            "unknown_on_hand_field": "must-not-escape",
        }
    )
    controls = project_inventory_control_exceptions(
        {
            "exceptions": [{"exception_id": "INVEX-1", "unknown_exception_field": "must-not-escape"}],
            "unknown_controls_field": "must-not-escape",
        }
    )
    summary = project_inventory_core_summary({"workspace": "default", "unknown_summary_field": "must-not-escape"})
    snapshot = project_inventory_core_snapshot(
        {
            "source": {"kind": "local-inventory-core", "unknown_source_field": "must-not-escape"},
            "summary": {"workspace": "default", "unknown_nested_summary_field": "must-not-escape"},
            "movements": [{"id": "movement-1", "unknown_nested_movement_field": "must-not-escape"}],
            "unknown_snapshot_field": "must-not-escape",
        }
    )

    assert movement.visible["lines"] == [{"id": "line-1", "quantity": "1.250", "quantity_scaled": 1250}]
    assert on_hand.visible["source"] == {"kind": "local-inventory-ledger"}
    assert on_hand.visible["balances"] == [{"item_code": "ITEM", "quantity_scaled": 2}]
    assert controls.visible["exceptions"] == [{"exception_id": "INVEX-1"}]
    assert summary.visible == {"workspace": "default"}
    assert snapshot.visible["summary"] == {"workspace": "default"}
    assert snapshot.visible["movements"] == [{"id": "movement-1"}]
    assert "must-not-escape" not in str([movement.visible, on_hand.visible, controls.visible, snapshot.visible])


def test_inventory_planning_projection_is_closed_recursively() -> None:
    session = project_inventory_planning_session(
        {
            "id": "count-1",
            "status": "Counting",
            "lines": [
                {
                    "id": "line-1",
                    "item_code": "ITEM-1",
                    "expected_quantity": "2.500",
                    "counted_quantity": "2.000",
                    "variance_quantity": "-0.500",
                    "unknown_line_field": "must-not-escape",
                }
            ],
            "summary": {"lines": 1, "counted_lines": 1, "variance_lines": 1, "unknown_summary_field": "must-not-escape"},
            "unknown_session_field": "must-not-escape",
        }
    )
    rule = project_inventory_reorder_rule(
        {
            "id": "rule-1",
            "item_code": "ITEM-1",
            "minimum_quantity": "3.000",
            "target_quantity": "5.000",
            "unknown_rule_field": "must-not-escape",
        }
    )
    signals = project_inventory_reorder_signals(
        {
            "schema_version": 1,
            "source": {"kind": "local-inventory-reorder-controls", "unknown_source_field": "must-not-escape"},
            "summary": {"total": 1, "high": 0, "medium": 1, "unknown_summary_field": "must-not-escape"},
            "pagination": {"limit": 100, "offset": 0, "returned": 1, "unknown_pagination_field": "must-not-escape"},
            "signals": [
                {
                    "signal_id": "signal-1",
                    "rule_id": "rule-1",
                    "risk_rating": "medium",
                    "item_code": "ITEM-1",
                    "suggested_quantity": "3.000",
                    "unknown_signal_field": "must-not-escape",
                }
            ],
            "unknown_signals_payload_field": "must-not-escape",
        }
    )
    snapshot = project_inventory_planning_snapshot(
        {
            "schema_version": 1,
            "source": {"kind": "local-inventory-planning", "unknown_source_field": "must-not-escape"},
            "workspace": "default",
            "summary": {
                "workspace": "default",
                "count_sessions": 1,
                "counting_sessions": 0,
                "submitted_sessions": 0,
                "approved_sessions": 0,
                "reorder_rules": 1,
                "active_reorder_rules": 1,
                "unknown_summary_field": "must-not-escape",
            },
            "count_sessions": [session.visible],
            "reorder_rules": [rule.visible],
            "unknown_snapshot_field": "must-not-escape",
        }
    )

    assert session.visible["lines"] == [
        {"expected_quantity": "2.500", "counted_quantity": "2.000", "variance_quantity": "-0.500", "id": "line-1", "item_code": "ITEM-1"}
    ]
    assert session.visible["summary"] == {"lines": 1, "counted_lines": 1, "variance_lines": 1}
    assert rule.visible == {"id": "rule-1", "item_code": "ITEM-1", "minimum_quantity": "3.000", "target_quantity": "5.000"}
    assert signals.visible["source"] == {"kind": "local-inventory-reorder-controls"}
    assert signals.visible["signals"] == [{"item_code": "ITEM-1", "risk_rating": "medium", "rule_id": "rule-1", "signal_id": "signal-1", "suggested_quantity": "3.000"}]
    assert snapshot.visible["summary"] == {
        "workspace": "default",
        "count_sessions": 1,
        "counting_sessions": 0,
        "submitted_sessions": 0,
        "approved_sessions": 0,
        "reorder_rules": 1,
        "active_reorder_rules": 1,
    }
    assert snapshot.visible["count_sessions"][0]["lines"] == session.visible["lines"]
    assert "must-not-escape" not in str([session.visible, rule.visible, signals.visible, snapshot.visible])


def test_inventory_planning_summary_projection_is_closed() -> None:
    result = project_inventory_planning_summary(
        {
            "workspace": "default",
            "count_sessions": 2,
            "counting_sessions": 1,
            "submitted_sessions": 1,
            "approved_sessions": 0,
            "reorder_rules": 3,
            "active_reorder_rules": 2,
            "unknown_summary_field": "must-not-escape",
        }
    )

    assert result.visible == {
        "workspace": "default",
        "count_sessions": 2,
        "counting_sessions": 1,
        "submitted_sessions": 1,
        "approved_sessions": 0,
        "reorder_rules": 3,
        "active_reorder_rules": 2,
    }
    assert result.denied_fields == ("unknown_summary_field",)


def test_individual_cashflow_projection_is_closed_recursively() -> None:
    result = project_individual_cashflow(
        {
            "schema_version": 1,
            "algorithm_version": "individual-cashflow-control-v1",
            "input_digests": ["a" * 64],
            "decision_digest": "b" * 64,
            "status_counts": {"over_budget": 1, "future_status": 9},
            "decisions": [
                {
                    "period": "2026-07",
                    "flow_type": "expense",
                    "category": "food",
                    "status": "over_budget",
                    "reason_code": "CASHFLOW_ACTIVITY_EXCEEDS_BUDGET",
                    "actual": {"amount": "25.00", "currency": "USD", "unknown_money_field": "must-not-escape"},
                    "budget": None,
                    "variance": {"amount": "5.00", "currency": "USD"},
                    "transaction_ids": ["tx-1"],
                    "unknown_decision_field": "must-not-escape",
                }
            ],
            "unknown_result_field": "must-not-escape",
        }
    )

    assert result.visible["status_counts"] == {"over_budget": 1}
    assert result.visible["decisions"] == [
        {
            "actual": {"amount": "25.00", "currency": "USD"},
            "budget": None,
            "category": "food",
            "flow_type": "expense",
            "period": "2026-07",
            "reason_code": "CASHFLOW_ACTIVITY_EXCEEDS_BUDGET",
            "status": "over_budget",
            "transaction_ids": ["tx-1"],
            "variance": {"amount": "5.00", "currency": "USD"},
        }
    ]
    assert "must-not-escape" not in str(result.visible)


def test_payables_supplier_projection_is_closed() -> None:
    result = project_payables_supplier(
        {"id": "supplier-1", "supplier_code": "SUP-1", "unknown_supplier_field": "must-not-escape"}
    )

    assert result.visible == {"id": "supplier-1", "supplier_code": "SUP-1"}
    assert result.denied_fields == ("unknown_supplier_field",)
    assert "must-not-escape" not in str(result.visible)


def test_professional_invoice_payment_projection_is_closed_recursively() -> None:
    result = project_professional_invoice_payment(
        {
            "id": "pip-1",
            "workspace_id": "firm-a",
            "unknown_run_field": "must-not-escape",
            "report": {
                "schema_version": 1,
                "decision_digest": "d" * 64,
                "amount_tolerance": {
                    "amount": "0.01",
                    "currency": "USD",
                    "unknown_money_field": "must-not-escape",
                },
                "decisions": [
                    {
                        "invoice_id": "INV-1",
                        "client_id": "CLIENT-1",
                        "status": "matched",
                        "payment_ids": ["PAY-1"],
                        "reason_code": "INVOICE_PAYMENT_RECONCILED",
                        "amount_variance": {
                            "amount": "0",
                            "currency": "USD",
                            "unknown_variance_field": "must-not-escape",
                        },
                        "unknown_decision_field": "must-not-escape",
                    }
                ],
                "status_counts": {"matched": 1, "future_status": 99},
                "unknown_report_field": "must-not-escape",
            },
        }
    )

    assert result.visible["report"] == {
        "amount_tolerance": {"amount": "0.01", "currency": "USD"},
        "decisions": [
            {
                "amount_variance": {"amount": "0", "currency": "USD"},
                "client_id": "CLIENT-1",
                "invoice_id": "INV-1",
                "payment_ids": ["PAY-1"],
                "reason_code": "INVOICE_PAYMENT_RECONCILED",
                "status": "matched",
            }
        ],
        "decision_digest": "d" * 64,
        "schema_version": 1,
        "status_counts": {"matched": 1},
    }
    assert result.denied_fields == ("unknown_run_field",)
    assert "must-not-escape" not in str(result.visible)


def test_retail_settlement_projection_is_closed_recursively() -> None:
    result = project_retail_settlement(
        {
            "id": "rtl-1",
            "workspace_id": "shop-a",
            "unknown_run_field": "must-not-escape",
            "report": {
                "schema_version": 1,
                "decision_digest": "d" * 64,
                "tolerance": {
                    "amount": "0.01",
                    "currency": "USD",
                    "unknown_money_field": "must-not-escape",
                },
                "decisions": [
                    {
                        "batch_id": "BATCH-1",
                        "store_id": "STORE-1",
                        "status": "matched",
                        "settlement_ids": ["SET-1"],
                        "reason_code": "SETTLEMENT_RECONCILED",
                        "net_variance": {
                            "amount": "0",
                            "currency": "USD",
                            "unknown_variance_field": "must-not-escape",
                        },
                        "unknown_decision_field": "must-not-escape",
                    }
                ],
                "status_counts": {"matched": 1, "future_status": 99},
                "unknown_report_field": "must-not-escape",
            },
        }
    )

    assert result.visible["report"] == {
        "decisions": [
            {
                "batch_id": "BATCH-1",
                "net_variance": {"amount": "0", "currency": "USD"},
                "reason_code": "SETTLEMENT_RECONCILED",
                "settlement_ids": ["SET-1"],
                "status": "matched",
                "store_id": "STORE-1",
            }
        ],
        "decision_digest": "d" * 64,
        "schema_version": 1,
        "status_counts": {"matched": 1},
        "tolerance": {"amount": "0.01", "currency": "USD"},
    }
    assert result.denied_fields == ("unknown_run_field",)
    assert "must-not-escape" not in str(result.visible)


def test_bank_statement_projection_is_closed_recursively() -> None:
    result = project_bank_statement(
        {
            "id": "bank-1",
            "workspace_id": "firm-a",
            "unknown_run_field": "must-not-escape",
            "report": {
                "schema_version": 1,
                "decision_digest": "d" * 64,
                "amount_tolerance": {
                    "amount": "0.01",
                    "currency": "EUR",
                    "unknown_money_field": "must-not-escape",
                },
                "date_window_days": 1,
                "decisions": [
                    {
                        "account_id": "ACCOUNT-1",
                        "amount_variance": {
                            "amount": "0.00",
                            "currency": "EUR",
                            "unknown_money_field": "must-not-escape",
                        },
                        "bank_line_id": "BANK-1",
                        "days_variance": 0,
                        "ledger_record_ids": ["LEDGER-1"],
                        "reason_code": "BANK_LEDGER_RECONCILED",
                        "status": "matched",
                        "unknown_decision_field": "must-not-escape",
                    }
                ],
                "status_counts": {"matched": 1, "future_status": 99},
                "unknown_report_field": "must-not-escape",
            },
        }
    )

    assert result.visible["report"] == {
        "amount_tolerance": {"amount": "0.01", "currency": "EUR"},
        "date_window_days": 1,
        "decision_digest": "d" * 64,
        "decisions": [
            {
                "account_id": "ACCOUNT-1",
                "amount_variance": {"amount": "0.00", "currency": "EUR"},
                "bank_line_id": "BANK-1",
                "days_variance": 0,
                "ledger_record_ids": ["LEDGER-1"],
                "reason_code": "BANK_LEDGER_RECONCILED",
                "status": "matched",
            }
        ],
        "schema_version": 1,
        "status_counts": {"matched": 1},
    }
    assert result.denied_fields == ("unknown_run_field",)
    assert "must-not-escape" not in str(result.visible)


def test_manufacturing_cost_control_projection_is_closed_recursively() -> None:
    result = project_manufacturing_cost_control(
        {
            "id": "mfg-1",
            "workspace_id": "plant-a",
            "unknown_run_field": "must-not-escape",
            "report": {
                "schema_version": 1,
                "decision_digest": "d" * 64,
                "amount_tolerance": {
                    "amount": "0.01",
                    "currency": "EUR",
                    "unknown_money_field": "must-not-escape",
                },
                "max_scrap_quantity": {"scale": 3, "unit": "PCS", "value": "2", "unknown_quantity_field": "must-not-escape"},
                "decisions": [
                    {
                        "order_id": "ORDER-1",
                        "product_id": "PRODUCT-1",
                        "status": "reconciled",
                        "reason_codes": ["MANUFACTURING_ORDER_RECONCILED"],
                        "planned_quantity": {"scale": 3, "unit": "PCS", "value": "10", "unknown_quantity_field": "must-not-escape"},
                        "issued_quantity": {"scale": 3, "unit": "PCS", "value": "10"},
                        "completed_quantity": {"scale": 3, "unit": "PCS", "value": "10"},
                        "scrap_quantity": {"scale": 3, "unit": "PCS", "value": "0"},
                        "expected_material_cost": {"amount": "100", "currency": "EUR", "unknown_money_field": "must-not-escape"},
                        "actual_material_cost": {"amount": "100", "currency": "EUR"},
                        "completion_cost": {"amount": "100", "currency": "EUR"},
                        "material_cost_variance": {"amount": "0", "currency": "EUR"},
                        "completion_cost_variance": {"amount": "0", "currency": "EUR"},
                        "unknown_decision_field": "must-not-escape",
                    }
                ],
                "status_counts": {"reconciled": 1, "future_status": 99},
                "unknown_report_field": "must-not-escape",
            },
        }
    )

    assert result.visible["report"] == {
        "amount_tolerance": {"amount": "0.01", "currency": "EUR"},
        "decisions": [
            {
                "actual_material_cost": {"amount": "100", "currency": "EUR"},
                "completed_quantity": {"scale": 3, "unit": "PCS", "value": "10"},
                "completion_cost": {"amount": "100", "currency": "EUR"},
                "completion_cost_variance": {"amount": "0", "currency": "EUR"},
                "expected_material_cost": {"amount": "100", "currency": "EUR"},
                "issued_quantity": {"scale": 3, "unit": "PCS", "value": "10"},
                "material_cost_variance": {"amount": "0", "currency": "EUR"},
                "order_id": "ORDER-1",
                "planned_quantity": {"scale": 3, "unit": "PCS", "value": "10"},
                "product_id": "PRODUCT-1",
                "reason_codes": ["MANUFACTURING_ORDER_RECONCILED"],
                "scrap_quantity": {"scale": 3, "unit": "PCS", "value": "0"},
                "status": "reconciled",
            }
        ],
        "decision_digest": "d" * 64,
        "max_scrap_quantity": {"scale": 3, "unit": "PCS", "value": "2"},
        "schema_version": 1,
        "status_counts": {"reconciled": 1},
    }
    assert result.denied_fields == ("unknown_run_field",)
    assert "must-not-escape" not in str(result.visible)


def test_payables_purchase_order_projection_is_closed_recursively() -> None:
    result = project_payables_purchase_order(
        {
            "id": "po-1",
            "lines": [{"id": "line-1", "ordered_quantity": "2.5", "unknown_line_field": "must-not-escape"}],
            "unknown_order_field": "must-not-escape",
        }
    )

    assert result.visible == {"id": "po-1", "lines": [{"id": "line-1", "ordered_quantity": "2.5"}]}
    assert result.denied_fields == ("unknown_order_field",)
    assert "must-not-escape" not in str(result.visible)


def test_payables_receipt_projection_is_closed_recursively() -> None:
    result = project_payables_receipt(
        {
            "id": "receipt-1",
            "lines": [{"id": "line-1", "received_quantity": "2", "unknown_line_field": "must-not-escape"}],
            "unknown_receipt_field": "must-not-escape",
        }
    )

    assert result.visible == {"id": "receipt-1", "lines": [{"id": "line-1", "received_quantity": "2"}]}
    assert result.denied_fields == ("unknown_receipt_field",)
    assert "must-not-escape" not in str(result.visible)


def test_payables_supplier_invoice_and_match_projection_is_closed_recursively() -> None:
    invoice = project_payables_supplier_invoice(
        {
            "id": "invoice-1",
            "lines": [{"id": "line-1", "invoiced_quantity": "2", "unknown_line_field": "must-not-escape"}],
            "three_way_match": {"status": "Passed", "unknown_match_field": "must-not-escape"},
            "unknown_invoice_field": "must-not-escape",
        }
    )
    match = project_payables_three_way_match(
        {"status": "Passed", "unknown_match_field": "must-not-escape"}
    )

    assert invoice.visible == {
        "id": "invoice-1",
        "lines": [{"id": "line-1", "invoiced_quantity": "2"}],
        "three_way_match": {"status": "Passed"},
    }
    assert match.visible == {"status": "Passed"}
    assert invoice.denied_fields == ("unknown_invoice_field",)
    assert "must-not-escape" not in str([invoice.visible, match.visible])


def test_receivables_projection_is_closed_recursively() -> None:
    customer = project_receivables_customer(
        {"id": "customer-1", "customer_code": "CUS-1", "unknown_customer_field": "must-not-escape"}
    )
    invoice = project_receivables_invoice(
        {
            "id": "invoice-1",
            "lines": [{"id": "line-1", "quantity": "2", "unknown_line_field": "must-not-escape"}],
            "unknown_invoice_field": "must-not-escape",
        }
    )
    receipt = project_receivables_receipt(
        {
            "id": "receipt-1",
            "allocations": [{"id": "allocation-1", "amount_minor": 10, "unknown_allocation_field": "must-not-escape"}],
            "unknown_receipt_field": "must-not-escape",
        }
    )
    exposure = project_receivables_credit_exposure(
        {"customer_code": "CUS-1", "exposure_minor": 10, "unknown_exposure_field": "must-not-escape"}
    )
    aging = project_receivables_aging(
        {
            "items": [{"invoice_id": "invoice-1", "outstanding_minor": 10, "unknown_item_field": "must-not-escape"}],
            "unknown_aging_field": "must-not-escape",
        }
    )

    assert customer.visible == {"customer_code": "CUS-1", "id": "customer-1"}
    assert invoice.visible["lines"] == [{"id": "line-1", "quantity": "2"}]
    assert receipt.visible["allocations"] == [{"amount_minor": 10, "id": "allocation-1"}]
    assert exposure.visible == {"customer_code": "CUS-1", "exposure_minor": 10}
    assert aging.visible["items"] == [{"invoice_id": "invoice-1", "outstanding_minor": 10}]
    assert "must-not-escape" not in str([customer.visible, invoice.visible, receipt.visible, exposure.visible, aging.visible])


def test_master_data_projection_closes_snapshot_and_nested_resource_fields() -> None:
    result = project_master_snapshot(
        {
            "schema_version": 1,
            "generated_at": "2026-08-26T00:00:00Z",
            "source": {"kind": "local-sqlite-master-data", "unknown_source_field": "must-not-escape"},
            "summary": {
                "workspace": "default",
                "organizations": 1,
                "unknown_summary_field": "must-not-escape",
            },
            "currencies": [
                {
                    "code": "USD",
                    "name": "US Dollar",
                    "minor_units": 2,
                    "unknown_currency_field": "must-not-escape",
                }
            ],
            "unknown_snapshot_field": "must-not-escape",
        }
    )
    assert result.visible["currencies"] == [{"code": "USD", "minor_units": 2, "name": "US Dollar"}]
    assert result.visible["summary"] == {"organizations": 1, "workspace": "default"}
    assert "unknown_source_field" not in str(result.visible)
    assert "unknown_summary_field" not in str(result.visible)
    assert "unknown_currency_field" not in str(result.visible)
    assert result.denied_fields == ("unknown_snapshot_field",)


def test_master_data_summary_projection_is_closed() -> None:
    result = project_master_summary(
        {
            "workspace": "default",
            "organizations": 1,
            "legal_entities": 2,
            "branches": 3,
            "periods": 4,
            "active_currencies": 5,
            "source": {"kind": "local-sqlite-master-data"},
            "unsupported_collections": ["exchange_rates"],
            "unknown_summary_field": "must-not-escape",
        }
    )

    assert result.visible == {
        "workspace": "default",
        "organizations": 1,
        "legal_entities": 2,
        "branches": 3,
        "periods": 4,
        "active_currencies": 5,
        "source": {"kind": "local-sqlite-master-data"},
        "unsupported_collections": ["exchange_rates"],
    }
    assert result.denied_fields == ("unknown_summary_field",)


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


def test_consolidation_ownership_projection_is_closed_for_single_and_effective_shapes() -> None:
    interest = {
        "interest_id": "OWN-1",
        "parent_entity_code": "PARENT",
        "subsidiary_entity_code": "SUB",
        "direct_ownership_percentage": "0.8",
        "effective_from": "2026-01-01",
        "effective_to": "",
        "version": "1.0.0",
        "source_digest": "a" * 64,
        "prepared_by": "maker",
        "approved_by": "checker",
        "approved_at": "2026-01-01T00:00:00Z",
        "unknown_future_column": "must-not-escape",
    }
    single = project_consolidation_ownership_interest_response(
        {
            "interest": interest,
            "source": {"kind": "sqlite", "workspace": "default", "unknown_source": "x"},
            "unknown_response_field": "must-not-escape",
        }
    )
    effective = project_consolidation_ownership_effective_response(
        {
            "interests": [interest],
            "source": {"kind": "postgresql", "server_mode": True, "unknown_source": "x"},
            "unknown_response_field": "must-not-escape",
        }
    )
    assert single.visible["interest"]["interest_id"] == "OWN-1"
    assert single.visible["source"] == {"kind": "sqlite", "workspace": "default"}
    assert effective.visible["interests"] == [{key: value for key, value in interest.items() if key != "unknown_future_column"}]
    assert effective.visible["source"] == {"kind": "postgresql", "server_mode": True}
    assert "must-not-escape" not in str(single.visible | effective.visible)


def test_consolidation_ppa_projection_is_closed_through_nested_money_and_bridge() -> None:
    result = project_consolidation_ppa_response(
        {
            "artifact": {
                "id": "ppa-1",
                "posted": False,
                "result_payload": {
                    "posted": False,
                    "book_net_assets": {"amount": "10", "currency": "USD", "future_money": "x"},
                    "items": [
                        {
                            "item_id": "item-1",
                            "fair_value": {"amount": "10", "currency": "USD", "future_money": "x"},
                            "future_item": "must-not-escape",
                        }
                    ],
                    "bridge": {
                        "posted": False,
                        "lines": [
                            {
                                "line_type": "consideration",
                                "amount": {"amount": "10", "currency": "USD", "future_money": "x"},
                                "future_line": "must-not-escape",
                            }
                        ],
                        "future_bridge": "must-not-escape",
                    },
                    "future_result": "must-not-escape",
                },
                "future_artifact": "must-not-escape",
            },
            "source": {"kind": "postgresql-consolidation-ppa", "future_source": "x"},
            "future_response": "must-not-escape",
        }
    )
    artifact = result.visible["artifact"]
    payload = artifact["result_payload"]
    assert artifact["id"] == "ppa-1"
    assert payload["book_net_assets"] == {"amount": "10", "currency": "USD"}
    assert payload["items"] == [
        {"item_id": "item-1", "fair_value": {"amount": "10", "currency": "USD"}}
    ]
    assert payload["bridge"]["lines"] == [
        {"amount": {"amount": "10", "currency": "USD"}, "line_type": "consideration"}
    ]
    assert result.visible["source"] == {"kind": "postgresql-consolidation-ppa"}
    assert "must-not-escape" not in str(result.visible)
