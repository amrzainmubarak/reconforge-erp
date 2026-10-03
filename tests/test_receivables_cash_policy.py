"""Resource-bound cash authority without widening the manage permission."""
from dataclasses import replace

import pytest

from reconforge.auth.policy import (
    POLICY_VERSION,
    CentralPolicyEngine,
    PolicyEvaluationContext,
    verify_policy_decision_evidence,
)
from tests.test_master_data_authority_policy import LEGACY_V1

# Captured from the unmodified committed v2 evaluator, not recomputed by v3.
LEGACY_V2 = {
    "actor_digest": "c807257045aeb03028a7b3eb310c07d78eee2c0f7c64306adf0a097e7af2156b",
    "allowed": True, "context_binding": "bound",
    "context_digest": "a59982e9bb58bab7aab688a34d06de5cf5445b8b27af5d66a9f1784069e3b28c",
    "evaluator": "CentralPolicyEngine",
    "granted_permission_digest": "fb5ccad5f3c62c9493ae2db165b843f797bcbaa10348b09f0afe842249797ec2",
    "policy_version": "central-policy-v2", "principal_type": "user", "reason_code": "policy_allowed",
    "request_id_digest": "eee139da3a33404ab26df0e99ce6afd46245b38e1275d2091cce24038237a6c6",
    "required_permission_digest": "433ec352c6670689717b49307f853a386a7b71411a2f9b6c06c48f85f3f592fc",
    "schema_version": 1,
    "scope_digest": "24dc6cd94cdd2e41b17b4b71b65f948e800cf3c8e7f47bb43265b30d4696fb8e",
    "surface_digest": "300c17655d97dc303740d8d1132c92676fdcd8a18fbc85dcf336a298722487be",
    "decision_digest": "6c9e87f35e7fd47993ab7977df991a1254c03093c42d7f784e3d2b943f92a474",
}


@pytest.mark.parametrize("action", ["post", "allocate"])
def test_cash_requires_human_and_recent_auth_even_without_caller_stepup_flag(action: str) -> None:
    engine = CentralPolicyEngine()
    context = PolicyEvaluationContext(user_id="cash-human", username="cash-human", user_permissions={"receivables.manage"}, object_type="receivables.receipt", action=action)
    assert engine.evaluate(context, required_permission="receivables.manage").reason_code == "step_up_required"
    authenticated = replace(context, step_up_active=True, step_up_method="password")
    assert engine.evaluate(authenticated, required_permission="receivables.manage").allowed
    assert engine.evaluate(replace(authenticated, principal_type="service_account"), required_permission="receivables.manage").reason_code == "human_principal_required"
    assert engine.evaluate(replace(authenticated, required_step_up_method="webauthn_user_verified"), required_permission="receivables.manage").reason_code == "mfa_required"
    assert engine.evaluate(replace(authenticated, user_permissions=set()), required_permission="receivables.manage").reason_code == "permission_missing"


def test_service_manage_non_cash_and_receipt_read_remain_authorized() -> None:
    context = PolicyEvaluationContext(user_id="cash-service", username="cash-service", user_permissions={"receivables.manage", "receivables.read"}, principal_type="service_account", step_up_enforced=True)
    engine = CentralPolicyEngine()
    assert engine.evaluate(context, required_permission="receivables.manage").allowed
    assert engine.evaluate(replace(context, object_type="receivables.receipt", action="read"), required_permission="receivables.read").allowed


def test_v3_reads_original_v1_v2_evidence_without_rewriting_digests() -> None:
    assert POLICY_VERSION == "central-policy-v3"
    for original in (LEGACY_V1, LEGACY_V2):
        assert verify_policy_decision_evidence(original) == original
        with pytest.raises(ValueError, match="digest mismatch"):
            verify_policy_decision_evidence({**original, "allowed": False})
