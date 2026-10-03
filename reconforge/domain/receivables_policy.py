"""Pure, retained AR monetary interpretation; never consult the live registry."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

from reconforge.domain.finance_policy import (
    POLICY_COLUMNS,
    FinanceCurrencyPolicy,
    FinancePolicyError,
    verified_registry_context,
)
from reconforge.utils.money import CurrencyRegistryContext, InvalidAmountError

_CURRENCY = re.compile(r"[A-Z]{3}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
AR_MONETARY_POLICY_SCHEMA_VERSION = 1


class ReceivablesPolicyError(ValueError):
    """Stable monetary-policy rejection without adapter or private record details."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ReceivablesMonetaryPolicy:
    """Verified policy plus retained public provenance, or explicit legacy absence."""

    currency_code: str
    captured: FinanceCurrencyPolicy | None = None
    policy_digest: str | None = None
    source: str | None = None
    source_url: str | None = None
    published_at: str | None = None

    def public_metadata(self) -> dict[str, object]:
        """Closed projection: no source record, snapshot or actor fields escape."""

        policy = self.captured
        return {
            "schema_version": AR_MONETARY_POLICY_SCHEMA_VERSION,
            "status": "unverified" if policy is None else "captured",
            "currency_code": self.currency_code,
            "precision": None if policy is None else policy.precision,
            "rounding_policy": None if policy is None else policy.rounding_policy,
            "registry_version": None if policy is None else policy.registry_version,
            "registry_digest": None if policy is None else policy.registry_digest,
            "policy_digest": None if policy is None else self.policy_digest,
            "source": None if policy is None else self.source,
            "source_url": None if policy is None else self.source_url,
            "published_at": None if policy is None else self.published_at,
        }

    def require_captured(self) -> FinanceCurrencyPolicy:
        if self.captured is None:
            raise ReceivablesPolicyError(
                "ar_monetary_policy_unverified",
                "Retained minor units have no verified historical policy; obtain reviewed policy evidence before a new financial effect.",
            )
        return self.captured


def verify_receivables_policy(
    record: Mapping[str, object], *, snapshot: object = None,
) -> ReceivablesMonetaryPolicy:
    """Verify one record against its own retained snapshot, with no fallback.

    A caller may supply the verified context returned by FinancePolicyStore; it
    is revalidated without installing or selecting a current registry. Absent
    legacy fields remain unresolved even when a present-day snapshot is passed.
    """

    currency = record.get("currency_code")
    values = tuple(record.get(column) for column in POLICY_COLUMNS)
    if all(value is None for value in values):
        # Legacy local records may contain three Unicode alphabetic letters.
        # Preserve their raw identity; absent evidence never establishes scale.
        return ReceivablesMonetaryPolicy(str(currency or ""))
    if not isinstance(currency, str) or not _CURRENCY.fullmatch(currency):
        raise ReceivablesPolicyError("ar_monetary_policy_invalid", "The retained currency code is invalid.")
    precision, rounding, version, digest = values
    if (
        any(value is None for value in values)
        or type(precision) is not int or not 0 <= precision <= 8
        or rounding != "ROUND_HALF_UP"
        or not isinstance(version, str) or not 1 <= len(version) <= 128
        or not isinstance(digest, str) or not _DIGEST.fullmatch(digest)
    ):
        raise ReceivablesPolicyError("ar_monetary_policy_invalid", "The retained policy fields are incomplete or invalid.")
    try:
        payload = snapshot.snapshot() if isinstance(snapshot, CurrencyRegistryContext) else snapshot
        context = verified_registry_context(payload)
        policy = FinanceCurrencyPolicy.verify_record(record, context)
        manifest = context.registry_manifest
        return ReceivablesMonetaryPolicy(
            currency, policy, context.resolve(currency).policy_digest,
            manifest.source, manifest.source_url, manifest.published_at,
        )
    except (FinancePolicyError, InvalidAmountError) as exc:
        raise ReceivablesPolicyError(
            "ar_monetary_policy_invalid", "The policy does not match verified retained registry evidence.",
        ) from exc


def require_policy_affinity(
    selected: ReceivablesMonetaryPolicy, *parents: ReceivablesMonetaryPolicy,
) -> FinanceCurrencyPolicy:
    """Require full provenance affinity, including newly selected write policy."""

    policy = selected.require_captured()
    for parent in parents:
        other = parent.require_captured()
        try:
            policy.require_compatible(other)
        except FinancePolicyError as exc:
            raise ReceivablesPolicyError(
                "ar_monetary_policy_mismatch",
                "Customer, invoice, receipt and selected write policy must have compatible retained monetary evidence.",
            ) from exc
    return policy


def require_expected_registry(
    policy: ReceivablesMonetaryPolicy, expected_digest: str | None,
) -> None:
    """Guard an optional major-unit client's policy precondition before effects."""

    if expected_digest is None:
        return
    if not isinstance(expected_digest, str) or not _DIGEST.fullmatch(expected_digest):
        raise ReceivablesPolicyError("ar_monetary_policy_invalid", "The expected registry digest is invalid.")
    if policy.require_captured().registry_digest != expected_digest:
        raise ReceivablesPolicyError(
            "ar_monetary_policy_changed", "Reload the authoritative monetary policy before confirming the amount.",
        )


def require_aggregation_affinity(policies: list[ReceivablesMonetaryPolicy]) -> None:
    """Keep legacy raw reports readable; never mix different retained scales."""

    by_currency: dict[str, ReceivablesMonetaryPolicy] = {}
    for policy in policies:
        previous = by_currency.setdefault(policy.currency_code, policy)
        if policy.captured is None and previous.captured is None:
            continue
        require_policy_affinity(previous, policy)


def require_replay_policy(response: Mapping[str, object], authoritative: ReceivablesMonetaryPolicy) -> None:
    """Cached lifecycle state may be old; its immutable interpretation may not."""

    expected = {
        "currency_code": authoritative.currency_code,
        **(dict.fromkeys(POLICY_COLUMNS) if authoritative.captured is None else authoritative.captured.metadata()),
    }
    retained = {field: response.get(field) for field in expected}
    projection = response.get("monetary_policy")
    try:
        def canonical(value: object) -> str:
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)

        valid = canonical(retained) == canonical(expected)
        if projection is None:
            valid = valid and authoritative.captured is None
        else:
            valid = valid and canonical(projection) == canonical(authoritative.public_metadata())
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ReceivablesPolicyError(
            "ar_monetary_policy_invalid", "Cached monetary interpretation differs from authoritative retained evidence.",
        )
