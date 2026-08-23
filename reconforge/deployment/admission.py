"""Composite, offline regulated-admission evidence gate."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from reconforge.deployment.key_custody import ManagedKeyManifest, verify_managed_key_manifest
from reconforge.deployment.profiles import DeploymentProfileError
from reconforge.deployment.runtime_evidence import (
    DeploymentRuntimeEvidence,
    verify_deployment_runtime_evidence,
)


class RegulatedAdmissionError(ValueError):
    """Raised when a composite regulated admission evidence envelope is unsafe."""


@dataclass(frozen=True)
class RegulatedAdmissionEvidence:
    """Verified local evidence for the regulated profile's declared prerequisites."""

    runtime: DeploymentRuntimeEvidence
    key_manifest: ManagedKeyManifest

    def __post_init__(self) -> None:
        if self.runtime.edition != "regulated":
            raise RegulatedAdmissionError("regulated admission requires the regulated edition")
        if self.runtime.findings:
            raise RegulatedAdmissionError("regulated runtime evidence contains unresolved profile findings")
        if not self.runtime.facts.customer_managed_keys_enabled:
            raise RegulatedAdmissionError("regulated admission requires customer-managed keys")
        if not self.key_manifest.customer_managed or self.key_manifest.provider == "local-development":
            raise RegulatedAdmissionError("regulated admission requires a non-local customer-managed key provider")

    def to_dict(self) -> dict[str, object]:
        return {
            "edition": self.runtime.edition,
            "profile_digest": self.runtime.profile_digest,
            "runtime_evidence_digest": self.runtime.digest,
            "key_manifest_digest": self.key_manifest.digest,
            "key_provider": self.key_manifest.provider,
            "key_scope": self.key_manifest.scope,
        }

    @property
    def digest(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def verify_regulated_admission(payload: Mapping[str, object]) -> RegulatedAdmissionEvidence:
    """Verify one strict composite envelope without network, secret, or KMS calls."""

    if not isinstance(payload, Mapping) or set(payload) != {"runtime_evidence", "key_manifest"}:
        raise RegulatedAdmissionError("regulated admission fields do not match the closed contract")
    runtime_payload = payload["runtime_evidence"]
    key_payload = payload["key_manifest"]
    if not isinstance(runtime_payload, Mapping) or not isinstance(key_payload, Mapping):
        raise RegulatedAdmissionError("regulated admission children must be objects")
    try:
        runtime = verify_deployment_runtime_evidence(cast(Mapping[str, object], runtime_payload))
        key_manifest = verify_managed_key_manifest(cast(Mapping[str, object], key_payload))
        return RegulatedAdmissionEvidence(runtime=runtime, key_manifest=key_manifest)
    except (DeploymentProfileError, ValueError, TypeError) as exc:
        if isinstance(exc, RegulatedAdmissionError):
            raise
        raise RegulatedAdmissionError(str(exc)) from exc


__all__ = ["RegulatedAdmissionError", "RegulatedAdmissionEvidence", "verify_regulated_admission"]
