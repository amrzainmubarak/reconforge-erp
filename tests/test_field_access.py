from reconforge.auth.field_access import REDACTED_VALUE, project_fields
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
