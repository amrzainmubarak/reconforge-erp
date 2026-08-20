"""Bounded reconciliation between persisted currency references and policy registry.

The canonical :class:`~reconforge.utils.money.CurrencyRegistry` is process
wide, while master-data currency references are tenant/workspace scoped by the
storage adapter.  This module deliberately does not mutate or silently switch
the installed registry.  It produces a deterministic, non-sensitive evidence
record so an operator can prove whether the selected master-data references
agree with the currently installed policy snapshot.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from reconforge.utils.money import (
    CurrencyRegistry,
    CurrencyRegistryContext,
    InvalidAmountError,
    UnknownCurrencyError,
)

_CODE_PATTERN = re.compile(r"^[A-Z]{3}$")
_REGISTRY_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}$")
_DIGEST_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_MAX_RECORDS = 100_000
_MAX_SCOPE_LENGTH = 160
_SCHEMA_VERSION = 1


class CurrencyRegistryGovernanceError(ValueError):
    """Raised when a reconciliation request cannot be bounded safely."""


@dataclass(frozen=True)
class CurrencyRegistryIssue:
    """One safe, deterministic reconciliation issue."""

    code: str
    currency_code: str
    message: str
    master_minor_units: int | None = None
    registry_minor_units: int | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "code": self.code,
            "currency_code": self.currency_code,
            "message": self.message,
        }
        if self.master_minor_units is not None:
            payload["master_minor_units"] = self.master_minor_units
        if self.registry_minor_units is not None:
            payload["registry_minor_units"] = self.registry_minor_units
        return payload


@dataclass(frozen=True)
class CurrencyRegistryReconciliation:
    """Digest-bound result for one tenant/workspace reference set."""

    schema_version: int
    scope: str
    registry_version: str
    registry_digest: str
    master_currency_count: int
    active_master_currency_count: int
    input_digest: str
    issues: tuple[CurrencyRegistryIssue, ...]
    binding: dict[str, object]

    @property
    def status(self) -> str:
        return "consistent" if not self.issues and self.binding["status"] in {"unbound", "current"} else "inconsistent"

    @property
    def ok(self) -> bool:
        return self.status == "consistent"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scope": self.scope,
            "status": self.status,
            "ok": self.ok,
            "registry": {
                "registry_version": self.registry_version,
                "digest": self.registry_digest,
            },
            "master_currency_count": self.master_currency_count,
            "active_master_currency_count": self.active_master_currency_count,
            "input_digest": self.input_digest,
            "issues": [issue.to_dict() for issue in self.issues],
            "binding": dict(self.binding),
        }


def _scope(value: object) -> str:
    normalized = " ".join(str(value or "").strip().split())
    if not normalized or len(normalized) > _MAX_SCOPE_LENGTH:
        raise CurrencyRegistryGovernanceError("currency registry reconciliation scope is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise CurrencyRegistryGovernanceError("currency registry reconciliation scope is invalid")
    return normalized


def _digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _active(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    return None


def _minor_units(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 6:
        return None
    return value


def _issue_sort_key(issue: CurrencyRegistryIssue) -> tuple[object, ...]:
    return (
        issue.currency_code,
        issue.code,
        issue.master_minor_units if issue.master_minor_units is not None else -1,
        issue.registry_minor_units if issue.registry_minor_units is not None else -1,
        issue.message,
    )


def _binding_payload(
    binding: Mapping[str, object] | None,
    *,
    registry_version: str,
    registry_digest: str,
) -> tuple[dict[str, object], CurrencyRegistryIssue | None]:
    """Normalize one persisted registry binding without trusting its fields."""

    if binding is None:
        return {"status": "unbound"}, None
    bound_version = str(binding.get("registry_version") or "").strip()
    bound_digest = str(binding.get("registry_digest") or "").strip().lower()
    bound_at = str(binding.get("bound_at") or "").strip()
    bound_by = str(binding.get("bound_by") or "").strip()
    if (
        _REGISTRY_VERSION_PATTERN.fullmatch(bound_version) is None
        or _DIGEST_PATTERN.fullmatch(bound_digest) is None
        or not bound_at
        or not bound_by
        or len(bound_at) > 64
        or len(bound_by) > 160
        or any(ord(character) < 32 or ord(character) == 127 for character in f"{bound_at}{bound_by}")
    ):
        return {
            "status": "invalid",
            "registry_version": "",
            "registry_digest": "",
        }, CurrencyRegistryIssue(
            code="registry_binding_invalid",
            currency_code="REGISTRY",
            message="persisted currency registry binding is malformed",
        )
    status = "current" if bound_version == registry_version and bound_digest == registry_digest else "drifted"
    return {
        "status": status,
        "registry_version": bound_version,
        "registry_digest": bound_digest,
        "bound_at": bound_at,
        "bound_by": bound_by,
    }, None


def reconcile_currency_registry(
    master_currencies: Iterable[Mapping[str, object]],
    *,
    scope: str,
    binding: Mapping[str, object] | None = None,
    registry_context: CurrencyRegistryContext | None = None,
    installed_registry_context: CurrencyRegistryContext | None = None,
) -> CurrencyRegistryReconciliation:
    """Compare bounded master-data rows with the installed currency policy.

    Rows are intentionally restricted to ``code``, ``minor_units`` and
    ``active``.  Unknown, malformed, duplicate, or precision-drifted rows are
    reported as issues rather than being coerced or dropped.  The function is
    order-independent and never includes names, amounts, tenant payloads, or
    other potentially sensitive fields in its result.
    """

    normalized_scope = _scope(scope)
    installed_context = installed_registry_context or CurrencyRegistry.context()
    operation_context = registry_context or installed_context
    manifest = operation_context.registry_manifest
    rows: list[dict[str, object]] = []
    issues: list[CurrencyRegistryIssue] = []
    seen_codes: set[str] = set()
    binding_payload, binding_issue = _binding_payload(
        binding,
        registry_version=installed_context.registry_manifest.registry_version,
        registry_digest=installed_context.registry_manifest.digest,
    )
    if binding_issue is not None:
        issues.append(binding_issue)

    for index, raw in enumerate(master_currencies):
        if index >= _MAX_RECORDS:
            raise CurrencyRegistryGovernanceError(f"currency registry reconciliation is limited to {_MAX_RECORDS} rows")
        if not isinstance(raw, Mapping):
            rows.append({"code": "INVALID", "minor_units": None, "active": None})
            issues.append(
                CurrencyRegistryIssue(
                    code="master_currency_invalid",
                    currency_code="INVALID",
                    message="master-data currency row is not an object",
                )
            )
            continue

        raw_code = raw.get("code")
        code = str(raw_code or "").strip().upper()
        safe_code = code if _CODE_PATTERN.fullmatch(code) else "INVALID"
        minor = _minor_units(raw.get("minor_units"))
        active = _active(raw.get("active"))
        rows.append({"code": safe_code, "minor_units": minor, "active": active})

        if safe_code == "INVALID":
            issues.append(
                CurrencyRegistryIssue(
                    code="master_currency_invalid",
                    currency_code="INVALID",
                    message="master-data currency code must contain exactly three letters",
                )
            )
            continue
        if safe_code in seen_codes:
            issues.append(
                CurrencyRegistryIssue(
                    code="master_currency_duplicate",
                    currency_code=safe_code,
                    message="master-data currency code appears more than once",
                )
            )
        seen_codes.add(safe_code)
        if minor is None:
            issues.append(
                CurrencyRegistryIssue(
                    code="master_currency_invalid",
                    currency_code=safe_code,
                    message="master-data minor_units must be an integer between 0 and 6",
                )
            )
            continue
        if active is None:
            issues.append(
                CurrencyRegistryIssue(
                    code="master_currency_invalid",
                    currency_code=safe_code,
                    message="master-data active flag must be boolean",
                    master_minor_units=minor,
                )
            )
            continue
        try:
            registry_spec = operation_context.get(safe_code)
        except UnknownCurrencyError:
            issues.append(
                CurrencyRegistryIssue(
                    code="registry_currency_missing",
                    currency_code=safe_code,
                    message="currency is present in master data but absent from the installed registry",
                    master_minor_units=minor,
                )
            )
            continue
        except InvalidAmountError as exc:
            raise CurrencyRegistryGovernanceError("installed currency registry is unavailable") from exc
        if registry_spec.minor_units != minor:
            issues.append(
                CurrencyRegistryIssue(
                    code="minor_units_mismatch",
                    currency_code=safe_code,
                    message="master-data precision differs from the installed registry",
                    master_minor_units=minor,
                    registry_minor_units=registry_spec.minor_units,
                )
            )

    canonical_rows = sorted(
        rows,
        key=lambda row: (
            str(row["code"]),
            row["minor_units"] if isinstance(row["minor_units"], int) else -1,
            row["active"] if isinstance(row["active"], bool) else False,
        ),
    )
    input_digest = _digest(
        {
            "schema_version": _SCHEMA_VERSION,
            "scope": normalized_scope,
            "registry_digest": manifest.digest,
            "registry_version": manifest.registry_version,
            "installed_registry_digest": installed_context.registry_manifest.digest,
            "installed_registry_version": installed_context.registry_manifest.registry_version,
            "binding": {
                "status": binding_payload["status"],
                "registry_version": binding_payload.get("registry_version"),
                "registry_digest": binding_payload.get("registry_digest"),
            },
            "master_currencies": canonical_rows,
        }
    )
    ordered_issues = tuple(sorted(issues, key=_issue_sort_key))
    return CurrencyRegistryReconciliation(
        schema_version=_SCHEMA_VERSION,
        scope=normalized_scope,
        registry_version=manifest.registry_version,
        registry_digest=manifest.digest,
        master_currency_count=len(rows),
        active_master_currency_count=sum(1 for row in rows if row["active"] is True),
        input_digest=input_digest,
        issues=ordered_issues,
        binding=binding_payload,
    )


__all__ = [
    "CurrencyRegistryGovernanceError",
    "CurrencyRegistryIssue",
    "CurrencyRegistryReconciliation",
    "reconcile_currency_registry",
]
