"""Independent retained zero/three-decimal provenance and closed projection."""

from __future__ import annotations

from copy import deepcopy

import pytest

from reconforge.domain.receivables_policy import (
    ReceivablesPolicyError,
    require_expected_registry,
    require_policy_affinity,
    require_replay_policy,
    verify_receivables_policy,
)
from reconforge.utils.money import CurrencyRegistryContext

SNAPSHOT = {
    "schema_version": 1, "registry_version": "synthetic-ar-policy-v1",
    "source": "Synthetic AR policy fixture", "source_url": "https://example.invalid/synthetic-ar-policy",
    "published_at": "2026-10-03",
    "currencies": [
        {"code": "JPY", "minor_units": 0, "name": "Synthetic yen", "numeric_code": "392", "rounding_policy": "ROUND_HALF_UP", "symbol": "JPY"},
        {"code": "KWD", "minor_units": 3, "name": "Synthetic dinar", "numeric_code": "414", "rounding_policy": "ROUND_HALF_UP", "symbol": "KWD"},
    ],
}
# SHA-256 oracles over the canonical fixture and each currency's semantic fields.
REGISTRY_DIGEST = "dc5c9369a7114fe54665b8b8c1304652d9df4c9d659bd65bd54f89cc223ec375"
POLICY_DIGESTS = {
    "JPY": "525ed89350cf907729c1090c6cca2c142e97ab528ed6d56ce67dac2c34a79225",
    "KWD": "5d83af4d137ee47efedfe54d3696db61112c8ebca6d01257762084960fadfc9f",
}
PUBLIC_FIELDS = {
    "schema_version", "status", "currency_code", "precision", "rounding_policy", "registry_version",
    "registry_digest", "policy_digest", "source", "source_url", "published_at",
}


def record(currency: str = "JPY") -> dict[str, object]:
    return {
        "currency_code": currency, "currency_precision": 0 if currency == "JPY" else 3,
        "currency_rounding_policy": "ROUND_HALF_UP", "currency_registry_version": "synthetic-ar-policy-v1",
        "currency_registry_digest": REGISTRY_DIGEST,
    }


@pytest.mark.parametrize("currency,precision", [("JPY", 0), ("KWD", 3)])
def test_captured_policy_has_exact_scale_and_source_without_current_registry(
    currency: str, precision: int, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden():
        raise AssertionError("A historical read must not select the installed registry")
    monkeypatch.setattr(CurrencyRegistryContext, "from_installed", forbidden)
    values = verify_receivables_policy(record(currency), snapshot=SNAPSHOT).public_metadata()
    assert values == {
        "schema_version": 1, "status": "captured", "currency_code": currency, "precision": precision,
        "rounding_policy": "ROUND_HALF_UP", "registry_version": "synthetic-ar-policy-v1",
        "registry_digest": REGISTRY_DIGEST, "policy_digest": POLICY_DIGESTS[currency],
        "source": "Synthetic AR policy fixture", "source_url": "https://example.invalid/synthetic-ar-policy",
        "published_at": "2026-10-03",
    }


@pytest.mark.parametrize("stored", [{"currency_code": "JPY"}, {"currency_code": "ΔΕΖ"}, {**record(), "currency_precision": None, "currency_rounding_policy": None, "currency_registry_version": None, "currency_registry_digest": None}])
def test_legacy_none_is_explicit_and_cannot_be_blessed_with_today_snapshot(stored: dict[str, object]) -> None:
    policy = verify_receivables_policy(stored, snapshot=SNAPSHOT)
    public = policy.public_metadata()
    assert set(public) == PUBLIC_FIELDS
    assert public["status"] == "unverified"
    assert all(public[key] is None for key in PUBLIC_FIELDS - {"schema_version", "status", "currency_code"})
    with pytest.raises(ReceivablesPolicyError, match="ar_monetary_policy_unverified"):
        policy.require_captured()
    with pytest.raises(ReceivablesPolicyError, match="ar_monetary_policy_unverified"):
        require_policy_affinity(verify_receivables_policy(record(), snapshot=SNAPSHOT), policy)


@pytest.mark.parametrize("field,value", [
    ("currency_precision", None), ("currency_precision", False), ("currency_precision", 0.0),
    ("currency_precision", -1), ("currency_precision", 9), ("currency_precision", 3),
    ("currency_rounding_policy", "ROUND_HALF_EVEN"), ("currency_registry_version", "other-version"),
    ("currency_registry_digest", "f" * 64), ("currency_registry_digest", "F" * 64),
])
def test_partial_forged_or_mismatched_policy_fails_closed(field: str, value: object) -> None:
    with pytest.raises(ReceivablesPolicyError, match="ar_monetary_policy_invalid"):
        verify_receivables_policy({**record(), field: value}, snapshot=SNAPSHOT)


@pytest.mark.parametrize("snapshot", [None, {}, "{malformed", {**SNAPSHOT, "digest": "f" * 64}])
def test_captured_policy_requires_verified_snapshot(snapshot: object) -> None:
    with pytest.raises(ReceivablesPolicyError, match="ar_monetary_policy_invalid"):
        verify_receivables_policy(record(), snapshot=snapshot)


def test_same_currency_scale_after_source_rebind_is_not_silent_affinity() -> None:
    historical = verify_receivables_policy(record(), snapshot=SNAPSHOT)
    rebound = deepcopy(SNAPSHOT)
    rebound["source"] = "Different retained provenance"
    context = CurrencyRegistryContext.from_snapshot(rebound)
    selected = verify_receivables_policy(
        {**record(), "currency_registry_digest": context.registry_manifest.digest}, snapshot=context,
    )
    assert selected.captured is not None and historical.captured is not None
    assert selected.captured.precision == historical.captured.precision == 0
    with pytest.raises(ReceivablesPolicyError, match="ar_monetary_policy_mismatch"):
        require_policy_affinity(selected, historical)
    assert historical.public_metadata()["source"] == "Synthetic AR policy fixture"


def test_invoice_receipt_customer_affinity_and_expected_registry_precondition() -> None:
    policy = verify_receivables_policy(record(), snapshot=SNAPSHOT)
    assert require_policy_affinity(policy, policy, policy) == policy.captured
    other = verify_receivables_policy(record("KWD"), snapshot=SNAPSHOT)
    with pytest.raises(ReceivablesPolicyError, match="ar_monetary_policy_mismatch"):
        require_policy_affinity(policy, other)
    require_expected_registry(policy, None)
    require_expected_registry(policy, REGISTRY_DIGEST)
    with pytest.raises(ReceivablesPolicyError, match="ar_monetary_policy_changed"):
        require_expected_registry(policy, "f" * 64)
    with pytest.raises(ReceivablesPolicyError, match="ar_monetary_policy_invalid"):
        require_expected_registry(policy, "not-a-digest")


def test_public_policy_is_closed_and_ignores_untrusted_record_metadata() -> None:
    untrusted = {**record(), "source": "forged", "snapshot_json": {"secret": "private"}, "source_path": "private/server/path", "future_private_field": "private"}
    public = verify_receivables_policy(untrusted, snapshot=SNAPSHOT).public_metadata()
    assert set(public) == PUBLIC_FIELDS
    assert public["source"] == "Synthetic AR policy fixture"
    assert "private" not in str(public) and "forged" not in str(public)


def test_backend_metadata_does_not_silently_expand_existing_http_contract() -> None:
    from reconforge.auth.field_access import (
        project_receivables_customer,
        project_receivables_invoice,
        project_receivables_receipt,
    )

    values = {"id": "synthetic", **record(), "monetary_policy": verify_receivables_policy(record(), snapshot=SNAPSHOT).public_metadata()}
    for projection in (project_receivables_customer, project_receivables_invoice, project_receivables_receipt):
        visible = projection(values).visible
        assert visible == {"id": "synthetic", "currency_code": "JPY"}


def test_legacy_replay_stays_unverified_without_invented_metadata() -> None:
    legacy = verify_receivables_policy({"currency_code": "ΔΕΖ"})
    require_replay_policy({"currency_code": "ΔΕΖ", "status": "Draft"}, legacy)
    require_replay_policy({"currency_code": "ΔΕΖ", "monetary_policy": legacy.public_metadata()}, legacy)
    with pytest.raises(ReceivablesPolicyError, match="policy_invalid"):
        require_replay_policy({"currency_code": "ΔΕΖ", "currency_precision": 2}, legacy)


@pytest.mark.parametrize("change", [{"currency_precision": False}, {"monetary_policy": None}, {"currency_code": "KWD"}])
def test_cached_policy_must_equal_verified_authority_with_exact_json_types(change: dict[str, object]) -> None:
    policy = verify_receivables_policy(record(), snapshot=SNAPSHOT)
    original = {**record(), "monetary_policy": policy.public_metadata(), "status": "Draft"}
    require_replay_policy(original, policy)
    with pytest.raises(ReceivablesPolicyError, match="policy_invalid"):
        require_replay_policy({**original, **change}, policy)
