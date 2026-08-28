"""Governed write-back lifecycle contracts; no provider or secret is used."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from string import ascii_letters, digits

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from reconforge.connectors.writeback import (
    WritebackAcknowledgement,
    WritebackApproval,
    WritebackError,
    WritebackIntent,
    WritebackPolicy,
    WritebackStatus,
    acknowledge_writeback,
    approve_writeback,
    complete_compensation,
    dispatch_writeback,
    dispatch_writeback_to_provider,
    request_compensation,
    validate_writeback_transition,
)

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)
POLICY = WritebackPolicy(
    connector_id="reference-rest-readonly",
    allowed_operations=frozenset({"payment.create"}),
    feature_enabled=True,
)


def _intent(**updates: object) -> WritebackIntent:
    values: dict[str, object] = {
        "schema_version": "connector-writeback-intent-v1",
        "intent_id": "intent-001",
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "connector_id": "reference-rest-readonly",
        "operation": "payment.create",
        "payload_digest": "a" * 64,
        "idempotency_key": "writeback-001",
        "requested_by": "maker-1",
        "requested_at": NOW,
        "feature_enabled": True,
    }
    values.update(updates)
    return WritebackIntent.model_validate(values)


def test_writeback_is_disabled_by_default_and_policy_is_fail_closed() -> None:
    intent = _intent(feature_enabled=False)
    with pytest.raises(WritebackError, match="feature_disabled"):
        POLICY.authorize(intent)
    with pytest.raises(WritebackError, match="feature_disabled"):
        dispatch_writeback(intent, policy=POLICY)


def test_self_approval_and_unsupported_operation_are_denied() -> None:
    with pytest.raises(WritebackError, match="self_approval"):
        approve_writeback(
            _intent(),
            policy=POLICY,
            actor_id="maker-1",
            approved_at=NOW,
            assurance="mfa",
            reason="not allowed",
        )


@given(
    actor=st.text(
        alphabet=ascii_letters + digits + "._@+-",
        min_size=1,
        max_size=20,
    )
)
def test_self_approval_is_denied_with_canonicalized_actor(actor: str) -> None:
    with pytest.raises(WritebackError, match="self_approval"):
        approve_writeback(
            _intent(requested_by=actor),
            policy=POLICY,
            actor_id=f"  {actor.swapcase()}  ",
            approved_at=NOW,
            assurance="mfa",
            reason="normalized actor is rejected",
        )


@given(
    actor=st.text(
        alphabet=ascii_letters + digits + "._@+-",
        min_size=1,
        max_size=20,
    )
)
def test_writeback_state_validation_rejects_canonicalized_approval_actor(actor: str) -> None:
    with pytest.raises(ValueError, match="requester cannot approve"):
        _intent(
            requested_by=actor,
            status=WritebackStatus.APPROVED,
            approval=WritebackApproval(
                actor_id=f"  {actor.swapcase()}  ",
                approved_at=NOW,
                assurance="mfa",
                reason="normalized actor is rejected",
            ),
        )
    unsupported = _intent(operation="journal.post")
    with pytest.raises(WritebackError, match="operation_not_allowed"):
        approve_writeback(
            unsupported,
            policy=POLICY,
            actor_id="checker-1",
            approved_at=NOW,
            assurance="step_up",
            reason="reviewed",
        )


def test_approved_dispatch_acknowledgement_and_compensation_are_bound() -> None:
    approved = approve_writeback(
        _intent(),
        policy=POLICY,
        actor_id="checker-1",
        approved_at=NOW,
        assurance="mfa",
        reason="two-person review",
    )
    assert approved.status is WritebackStatus.APPROVED
    dispatched = dispatch_writeback(approved, policy=POLICY)
    assert dispatched.status is WritebackStatus.DISPATCHED
    acknowledged = acknowledge_writeback(
        dispatched,
        provider_reference="provider-123",
        response_digest="b" * 64,
        acknowledged_at=NOW,
        accepted=True,
    )
    assert acknowledged.acknowledgement is not None
    compensation = request_compensation(acknowledged, reason="provider reversal required")
    completed = complete_compensation(
        compensation,
        acknowledgement=WritebackAcknowledgement(
            provider_reference="provider-reversal-123",
            acknowledged_at=NOW,
            response_digest="c" * 64,
            idempotency_key="writeback-001:compensation",
            accepted=True,
        ),
    )
    assert completed.status is WritebackStatus.COMPENSATED


def test_dispatch_and_acknowledgement_cannot_be_replayed_or_misbound() -> None:
    approved = approve_writeback(
        _intent(),
        policy=POLICY,
        actor_id="checker-1",
        approved_at=NOW,
        assurance="step_up",
        reason="reviewed",
    )
    dispatched = dispatch_writeback(approved, policy=POLICY)
    with pytest.raises(WritebackError, match="dispatch_requires_approval"):
        dispatch_writeback(dispatched, policy=POLICY)
    with pytest.raises(WritebackError, match="idempotency"):
        complete_compensation(
            request_compensation(dispatched, reason="rollback"),
            acknowledgement=WritebackAcknowledgement(
                provider_reference="provider-reversal-123",
                acknowledged_at=NOW,
                response_digest="c" * 64,
                idempotency_key="other-key",
                accepted=True,
            ),
        )


def test_compensation_rejected_acknowledgement_does_not_claim_compensated() -> None:
    approved = approve_writeback(
        _intent(),
        policy=POLICY,
        actor_id="checker-1",
        approved_at=NOW,
        assurance="mfa",
        reason="two-person review",
    )
    compensation = request_compensation(
        dispatch_writeback(approved, policy=POLICY), reason="rollback required"
    )
    with pytest.raises(WritebackError, match="compensation_not_accepted"):
        complete_compensation(
            compensation,
            acknowledgement=WritebackAcknowledgement(
                provider_reference="provider-reversal-rejected",
                acknowledged_at=NOW,
                response_digest="d" * 64,
                idempotency_key="writeback-001:compensation",
                accepted=False,
            ),
        )


def test_acknowledgement_requires_dispatched_state_and_exact_schema() -> None:
    with pytest.raises(WritebackError, match="acknowledgement_state"):
        acknowledge_writeback(
            _intent(),
            provider_reference="provider-123",
            response_digest="b" * 64,
            acknowledged_at=NOW,
            accepted=True,
        )
    with pytest.raises(ValidationError):
        _intent(payload_digest="not-a-digest")
    with pytest.raises(ValidationError):
        WritebackIntent.model_validate({**_intent().model_dump(mode="json"), "secret": "must-be-rejected"})


@dataclass
class _Transport:
    acknowledgement: WritebackAcknowledgement | None = None
    failure: bool = False

    def send(self, **kwargs: object) -> WritebackAcknowledgement:
        assert kwargs["idempotency_key"] == "writeback-001"
        if self.failure:
            raise RuntimeError("synthetic provider timeout")
        assert self.acknowledgement is not None
        return self.acknowledgement


def test_injected_provider_dispatch_binds_ack_and_failure_is_fail_closed() -> None:
    approved = approve_writeback(
        _intent(), policy=POLICY, actor_id="checker-1", approved_at=NOW, assurance="mfa", reason="reviewed"
    )
    dispatched = dispatch_writeback(approved, policy=POLICY)
    accepted = WritebackAcknowledgement(
        provider_reference="provider-123",
        acknowledged_at=NOW,
        response_digest="b" * 64,
        idempotency_key="writeback-001",
        accepted=True,
    )
    acknowledged = dispatch_writeback_to_provider(
        dispatched, policy=POLICY, transport=_Transport(acknowledgement=accepted)
    )
    assert acknowledged.status is WritebackStatus.ACKNOWLEDGED
    with pytest.raises(WritebackError, match="dispatch_failed"):
        dispatch_writeback_to_provider(dispatched, policy=POLICY, transport=_Transport(failure=True))


def test_injected_provider_ack_mismatch_is_rejected() -> None:
    approved = approve_writeback(
        _intent(), policy=POLICY, actor_id="checker-1", approved_at=NOW, assurance="step_up", reason="reviewed"
    )
    dispatched = dispatch_writeback(approved, policy=POLICY)
    mismatched = WritebackAcknowledgement(
        provider_reference="provider-123",
        acknowledged_at=NOW,
        response_digest="b" * 64,
        idempotency_key="other-key",
        accepted=True,
    )
    with pytest.raises(WritebackError, match="acknowledgement_mismatch"):
        dispatch_writeback_to_provider(
            dispatched, policy=POLICY, transport=_Transport(acknowledgement=mismatched)
        )


def test_digest_is_deterministic_and_payload_is_not_part_of_contract() -> None:
    first = _intent()
    second = _intent()
    assert first.digest == second.digest
    assert "payload" not in first.model_dump()


def test_proposal_digest_is_stable_across_authorized_lifecycle_versions() -> None:
    proposed = _intent()
    approved = approve_writeback(
        proposed,
        policy=POLICY,
        actor_id="checker-1",
        approved_at=NOW,
        assurance="mfa",
        reason="independent review",
    )
    dispatched = dispatch_writeback(approved, policy=POLICY)
    acknowledged = acknowledge_writeback(
        dispatched,
        provider_reference="provider-123",
        response_digest="b" * 64,
        acknowledged_at=NOW,
        accepted=True,
    )

    assert len({item.proposal_digest for item in (proposed, approved, dispatched, acknowledged)}) == 1
    assert len({item.digest for item in (proposed, approved, dispatched, acknowledged)}) == 4
    validate_writeback_transition(proposed, approved)
    validate_writeback_transition(approved, dispatched)
    validate_writeback_transition(dispatched, acknowledged)


@pytest.mark.parametrize(
    ("field", "changed_value"),
    [
        ("schema_version", "connector-writeback-intent-v2"),
        ("intent_id", "intent-002"),
        ("tenant_id", "tenant-b"),
        ("workspace_id", "workspace-b"),
        ("connector_id", "other-connector"),
        ("operation", "payment.update"),
        ("payload_digest", "f" * 64),
        ("idempotency_key", "writeback-002"),
        ("requested_by", "maker-2"),
        ("requested_at", NOW + timedelta(seconds=1)),
        ("feature_enabled", False),
    ],
)
def test_transition_rejects_drift_in_every_proposal_identity_field(
    field: str,
    changed_value: object,
) -> None:
    proposed = _intent()
    approved = approve_writeback(
        proposed,
        policy=POLICY,
        actor_id="checker-1",
        approved_at=NOW,
        assurance="mfa",
        reason="independent review",
    )
    drifted = approved.model_copy(update={field: changed_value})

    assert drifted.proposal_digest != proposed.proposal_digest
    with pytest.raises(WritebackError, match="writeback_proposal_identity_immutable"):
        validate_writeback_transition(proposed, drifted)


def test_transition_rejects_non_adjacent_state_even_when_proposal_is_unchanged() -> None:
    proposed = _intent()
    dispatched = dispatch_writeback(
        approve_writeback(
            proposed,
            policy=POLICY,
            actor_id="checker-1",
            approved_at=NOW,
            assurance="mfa",
            reason="independent review",
        ),
        policy=POLICY,
    )

    with pytest.raises(WritebackError, match="writeback_transition_invalid"):
        validate_writeback_transition(proposed, dispatched)
