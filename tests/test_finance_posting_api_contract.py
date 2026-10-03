"""Exact API money and evidence projections preserve the reviewed snapshot."""

import json
from dataclasses import replace

import pytest

from reconforge.api.finance_posting_contract import (
    project_posted_trial_balance,
    project_posting_effect,
    project_posting_preview,
)
from reconforge.api.routes.finance_posting import PostRequest, ReversalRequest
from reconforge.auth.policy import CentralPolicyEngine, PolicyEvaluationContext
from reconforge.domain.finance_posting import canonical_json, make_entry_snapshot, validation_digest


def snapshot():
    return make_entry_snapshot({
        "id": "GLE-large", "workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity",
        "journal_id": "journal", "period_id": "period", "entry_number": "LARGE",
        "posting_date": "2026-07-28", "description": "Synthetic exact entry", "external_reference": "",
        "source_type": "Manual", "currency_code": "USD", "currency_precision": 2,
        "currency_rounding_policy": "ROUND_HALF_UP", "currency_registry_version": "synthetic-v1",
        "currency_registry_digest": "c" * 64, "preparer_actor_id": "maker", "reverses_posting_id": None,
    }, [
        {"line_number": 1, "account_id": "cash", "description": "", "debit_minor": 9007199254740993, "credit_minor": 0, "dimensions": {"cost": "hq"}},
        {"line_number": 2, "account_id": "equity", "description": "", "debit_minor": 0, "credit_minor": 9007199254740993, "dimensions": {}},
    ])


def test_api_keeps_canonical_evidence_and_exact_money_beyond_js_integer_range() -> None:
    raw = snapshot()
    digest = validation_digest(raw)
    review = project_posting_preview({
        "entry_id": "GLE-large", "status": "Validated", "preparer_actor_id": "maker", "validator_actor_id": "checker",
        "validation_digest": digest, "validation_contract_version": raw["schema_version"], "reverses_posting_id": None,
        "current_content_digest": digest, "snapshot": raw, "driver_secret": "must-not-escape",
    })
    assert review["snapshot_json"] == canonical_json(raw)
    assert validation_digest(json.loads(review["snapshot_json"])) == digest
    assert review["lines"][0]["debit_minor"] == "9007199254740993"
    assert review["lines"][0]["credit_minor"] == "0"
    assert "snapshot" not in review and "driver_secret" not in review
    effect = {
        "id": "PST-large", "entry_id": "GLE-large", "source_kind": "Manual", "source_id": "GLE-large",
        "purpose": "operational_posting", "reverses_effect_id": None, "validation_digest": digest,
        "validation_contract_version": raw["schema_version"], "posted_actor_id": "checker", "posted_at": "2026-10-03T10:00:00Z",
        "reason": "Synthetic explicit posting", "audit_event_id": "audit", "outbox_event_id": "outbox", "snapshot": raw,
        "tenant_id": "must-not-escape", **{key: raw["entry"][key] for key in (
            "workspace_id", "organization_id", "legal_entity_id", "currency_code", "currency_precision",
            "currency_rounding_policy", "currency_registry_version", "currency_registry_digest",
        )},
    }
    projected = project_posting_effect(effect)
    assert "tenant_id" not in projected
    assert projected["snapshot_digest"] == digest
    with pytest.raises(ValueError, match="validation digest"):
        project_posting_effect({**effect, "validation_digest": "0" * 64})


def test_posted_balance_aggregates_remain_exact_and_closed() -> None:
    units = 18446744073709551614
    account = {"account_id": "cash", "debit_minor": units, "credit_minor": 0, "balance_minor": units, "debit_balance_minor": units, "credit_balance_minor": 0, "driver_secret": "hidden", "postings": [{
        "effect_id": effect_id, "entry_id": effect_id, "line_number": 1, "debit_minor": units // 2, "credit_minor": 0, "internal": "hidden",
    } for effect_id in ("effect-1", "effect-2")]}
    credit_account = {"account_id": "equity", "debit_minor": 0, "credit_minor": units, "balance_minor": -units, "debit_balance_minor": 0, "credit_balance_minor": units, "postings": [{
        "effect_id": effect_id, "entry_id": effect_id, "line_number": 2, "debit_minor": 0, "credit_minor": units // 2,
    } for effect_id in ("effect-1", "effect-2")]}
    raw = {"workspace_id": "work", "organization_code": "ORG", "entity_code": "E", "period_id": "p", "effect_count": 2,
           "currency_policy": None, "accounts": [account, credit_account], "totals": {"debit_minor": units, "credit_minor": units, "balanced": True}, "balance_totals": {"debit_minor": units, "credit_minor": units, "balanced": True}}
    result = project_posted_trial_balance(raw)
    assert result["turnover_totals"]["debit_minor"] == "18446744073709551614"
    assert result["balance_scope"] == "selected-period-net-activity"
    assert result["accounts"][0]["balance_minor"] == str(units)
    assert "driver_secret" not in result["accounts"][0]
    assert "internal" not in result["accounts"][0]["postings"][0]
    with pytest.raises(ValueError, match="exact integer"):
        project_posted_trial_balance({**raw, "totals": {"debit_minor": True, "credit_minor": True, "balanced": True}})
    with pytest.raises(ValueError, match="contributing evidence"):
        project_posted_trial_balance({**raw, "accounts": [{**account, "balance_minor": units - 1}, credit_account]})
    with pytest.raises(ValueError, match="contributing evidence"):
        project_posted_trial_balance({**raw, "effect_count": 3})


@pytest.mark.parametrize("permission", ["finance_core.post", "finance_core.reverse"])
def test_posting_authority_rejects_services_and_requires_recent_server_auth(permission: str) -> None:
    context = PolicyEvaluationContext(user_id="reviewer", username="reviewer", user_permissions={permission}, step_up_enforced=True)
    engine = CentralPolicyEngine()
    assert engine.evaluate(context, required_permission=permission).reason_code == "step_up_required"
    assert engine.evaluate(replace(context, step_up_active=True), required_permission=permission).allowed
    assert engine.evaluate(replace(context, principal_type="service_account", step_up_active=True), required_permission=permission).reason_code == "human_principal_required"


def test_posting_requests_do_not_accept_actor_or_hidden_assurance() -> None:
    with pytest.raises(ValueError):
        PostRequest(command_id="same-command", expected_validation_digest="a" * 64, reason="Explicit", actor_id="checker")
    with pytest.raises(ValueError):
        ReversalRequest(command_id="same-command", entry_number="REV", period_id="p", posting_date="2026-07-28", reason="Explicit", step_up_active=True)
