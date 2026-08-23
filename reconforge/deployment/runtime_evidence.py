"""Strict offline deployment runtime-evidence manifest verification.

The manifest is an operator evidence input, not a probe of external systems.
It binds one deployment edition to the exact runtime facts consumed by the
fail-closed profile validator and produces a deterministic digest for audit
and admission workflows.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from reconforge.deployment.profiles import (
    DeploymentEdition,
    DeploymentProfileError,
    DeploymentRuntimeFacts,
    validate_deployment_profile,
)


class DeploymentRuntimeEvidenceError(ValueError):
    """Raised when a runtime-evidence manifest violates its closed contract."""


_FACT_FIELDS = (
    "storage_backend",
    "identity_provider",
    "queue_backend",
    "object_store",
    "network_enabled",
    "writeback_enabled",
    "human_approval_enabled",
    "air_gap_enabled",
    "customer_managed_keys_enabled",
    "independent_failure_domains_verified",
    "worker_discovery_execution_separation_verified",
    "backup_restore_verified",
    "rollback_verified",
    "retention_privacy_verified",
)
_REQUIRED_FIELDS = frozenset(("edition", *_FACT_FIELDS))


@dataclass(frozen=True)
class DeploymentRuntimeEvidence:
    """Verified edition and runtime facts with a canonical evidence digest."""

    edition: DeploymentEdition
    facts: DeploymentRuntimeFacts

    def to_dict(self) -> dict[str, object]:
        return {"edition": self.edition, **self.facts.__dict__}

    @property
    def digest(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("ascii")).hexdigest()

    @property
    def findings(self) -> tuple[str, ...]:
        return validate_deployment_profile(self.edition, self.facts)


def verify_deployment_runtime_evidence(payload: Mapping[str, object]) -> DeploymentRuntimeEvidence:
    """Verify one strict JSON-shaped runtime-evidence manifest offline."""

    if not isinstance(payload, Mapping):
        raise DeploymentRuntimeEvidenceError("runtime evidence must be an object")
    if set(payload) != _REQUIRED_FIELDS:
        raise DeploymentRuntimeEvidenceError("runtime evidence fields do not match the closed contract")
    edition = payload["edition"]
    if not isinstance(edition, str):
        raise DeploymentRuntimeEvidenceError("edition must be a string")
    values: dict[str, object] = {field: payload[field] for field in _FACT_FIELDS}
    for field in _FACT_FIELDS:
        value = values[field]
        if field.endswith("_enabled") or field.endswith("_verified"):
            if not isinstance(value, bool):
                raise DeploymentRuntimeEvidenceError(f"{field} must be boolean")
        elif not isinstance(value, str):
            raise DeploymentRuntimeEvidenceError(f"{field} must be a string")
    try:
        facts = DeploymentRuntimeFacts(**cast(Any, values))
        # Validate edition while keeping the original profile error text useful.
        evidence = DeploymentRuntimeEvidence(edition=cast(DeploymentEdition, edition), facts=facts)
        _ = evidence.findings
    except (DeploymentProfileError, TypeError, ValueError) as exc:
        raise DeploymentRuntimeEvidenceError(str(exc)) from exc
    return evidence


__all__ = [
    "DeploymentRuntimeEvidence",
    "DeploymentRuntimeEvidenceError",
    "verify_deployment_runtime_evidence",
]
