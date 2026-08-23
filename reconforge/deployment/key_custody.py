"""Provider-neutral, non-secret managed-key custody evidence verification."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_PROVIDERS = frozenset({"aws-kms", "azure-key-vault", "customer-hsm", "gcp-kms", "local-development"})
_PURPOSES = frozenset({"backup", "evidence", "object-storage"})
_FIELDS = frozenset(
    {
        "provider",
        "key_id",
        "key_version",
        "algorithm",
        "purpose",
        "scope",
        "customer_managed",
        "status",
        "rotation_period_days",
    }
)


class ManagedKeyManifestError(ValueError):
    """Raised when a managed-key custody evidence manifest is unsafe."""


@dataclass(frozen=True)
class ManagedKeyManifest:
    provider: str
    key_id: str
    key_version: str
    algorithm: str
    purpose: str
    scope: str
    customer_managed: bool
    status: str
    rotation_period_days: int

    def __post_init__(self) -> None:
        for value, field in (
            (self.provider, "provider"),
            (self.key_id, "key_id"),
            (self.key_version, "key_version"),
            (self.algorithm, "algorithm"),
            (self.purpose, "purpose"),
            (self.scope, "scope"),
            (self.status, "status"),
        ):
            if not isinstance(value, str) or not _ID.fullmatch(value.strip()):
                raise ManagedKeyManifestError(f"{field} is invalid")
        if self.provider not in _PROVIDERS:
            raise ManagedKeyManifestError("provider is unsupported")
        if self.purpose not in _PURPOSES:
            raise ManagedKeyManifestError("purpose is unsupported")
        if self.algorithm != "AES-256-GCM":
            raise ManagedKeyManifestError("algorithm is unsupported")
        if self.status != "active":
            raise ManagedKeyManifestError("key status must be active")
        if not self.customer_managed:
            raise ManagedKeyManifestError("customer_managed must be true")
        if isinstance(self.rotation_period_days, bool) or not isinstance(self.rotation_period_days, int):
            raise ManagedKeyManifestError("rotation_period_days must be an integer")
        if not 1 <= self.rotation_period_days <= 3650:
            raise ManagedKeyManifestError("rotation_period_days is outside the allowed range")

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm": self.algorithm,
            "customer_managed": self.customer_managed,
            "key_id": self.key_id,
            "key_version": self.key_version,
            "provider": self.provider,
            "purpose": self.purpose,
            "rotation_period_days": self.rotation_period_days,
            "scope": self.scope,
            "status": self.status,
        }

    @property
    def digest(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def verify_managed_key_manifest(payload: Mapping[str, object]) -> ManagedKeyManifest:
    """Verify one non-secret managed-key custody manifest offline."""

    if not isinstance(payload, Mapping) or set(payload) != _FIELDS:
        raise ManagedKeyManifestError("managed-key manifest fields do not match the closed contract")
    try:
        return ManagedKeyManifest(
            provider=cast(str, payload["provider"]),
            key_id=cast(str, payload["key_id"]),
            key_version=cast(str, payload["key_version"]),
            algorithm=cast(str, payload["algorithm"]),
            purpose=cast(str, payload["purpose"]),
            scope=cast(str, payload["scope"]),
            customer_managed=cast(bool, payload["customer_managed"]),
            status=cast(str, payload["status"]),
            rotation_period_days=cast(int, payload["rotation_period_days"]),
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ManagedKeyManifestError):
            raise
        raise ManagedKeyManifestError(str(exc)) from exc


__all__ = ["ManagedKeyManifest", "ManagedKeyManifestError", "verify_managed_key_manifest"]
