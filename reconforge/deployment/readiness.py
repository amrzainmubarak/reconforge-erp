"""Offline, fail-closed reader for the deployment readiness evidence matrix."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from reconforge.io.structured import StructuredDocumentError, read_yaml_document

_EDITIONS = ("community", "team", "enterprise", "regulated")
_GATES = (
    "backup_restore",
    "rollback",
    "retention_privacy",
    "identity_and_worker_governance",
    "external_dependency_boundary",
    "failure_domain_and_dr",
    "sovereign_air_gap",
    "customer_managed_keys",
)
_STATUSES = frozenset({"verified_scoped", "partial", "open"})
_TOP_LEVEL = frozenset(
    {"schema_version", "matrix_id", "reviewed_on", "claim_boundary", "status_values", "required_gates", "editions"}
)
_EDITION_FIELDS = frozenset({"id", "readiness_status", "profile_command", "gates"})
_GATE_FIELDS = frozenset({"id", "status", "evidence", "boundary"})


class DeploymentReadinessError(ValueError):
    """Raised when a readiness matrix is unsafe or violates its contract."""


@dataclass(frozen=True)
class DeploymentReadinessMatrix:
    """Verified matrix payload and deterministic digest."""

    payload: Mapping[str, object]
    source_path: Path
    root: Path

    @property
    def matrix_id(self) -> str:
        return cast(str, self.payload["matrix_id"])

    @property
    def digest(self) -> str:
        encoded = json.dumps(self.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @property
    def editions(self) -> tuple[Mapping[str, object], ...]:
        return cast(tuple[Mapping[str, object], ...], tuple(cast(list[Mapping[str, object]], self.payload["editions"])))

    def select(self, edition: str | None = None) -> tuple[Mapping[str, object], ...]:
        if edition is None:
            return self.editions
        normalized = edition.strip().lower()
        if normalized not in _EDITIONS:
            raise DeploymentReadinessError("deployment edition is unsupported")
        return tuple(item for item in self.editions if item["id"] == normalized)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise DeploymentReadinessError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _relative_evidence_path(value: object, *, root: Path) -> None:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise DeploymentReadinessError("evidence paths must be relative")
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise DeploymentReadinessError("evidence path escapes repository root") from exc
    if not candidate.is_file():
        raise DeploymentReadinessError("evidence path does not resolve to a regular file")


def _verify_payload(payload: object, *, root: Path) -> Mapping[str, object]:
    top = _mapping(payload, "readiness matrix")
    if set(top) != _TOP_LEVEL:
        raise DeploymentReadinessError("readiness matrix fields do not match the closed contract")
    if top["schema_version"] != 1 or top["matrix_id"] != "reconforge-deployment-readiness":
        raise DeploymentReadinessError("readiness matrix identity is invalid")
    status_values = top["status_values"]
    if not isinstance(status_values, list) or tuple(cast(list[object], status_values)) != (
        "verified_scoped",
        "partial",
        "open",
    ):
        raise DeploymentReadinessError("readiness matrix status contract is invalid")
    required_gates = top["required_gates"]
    if not isinstance(required_gates, list) or tuple(cast(list[object], required_gates)) != _GATES:
        raise DeploymentReadinessError("readiness matrix gate contract is invalid")
    editions = top["editions"]
    if not isinstance(editions, list) or len(editions) != len(_EDITIONS):
        raise DeploymentReadinessError("readiness matrix editions are invalid")
    seen_editions: set[str] = set()
    for raw_edition in editions:
        edition = _mapping(raw_edition, "edition")
        if set(edition) != _EDITION_FIELDS:
            raise DeploymentReadinessError("edition fields do not match the closed contract")
        edition_id = edition["id"]
        if not isinstance(edition_id, str) or edition_id not in _EDITIONS or edition_id in seen_editions:
            raise DeploymentReadinessError("edition identity is invalid")
        seen_editions.add(edition_id)
        if edition["readiness_status"] not in {"partial", "open"}:
            raise DeploymentReadinessError("edition readiness status cannot claim readiness")
        gates = edition["gates"]
        if not isinstance(gates, list) or len(gates) != len(_GATES):
            raise DeploymentReadinessError("edition gates are invalid")
        seen_gates: set[str] = set()
        for raw_gate in gates:
            gate = _mapping(raw_gate, "gate")
            if set(gate) != _GATE_FIELDS:
                raise DeploymentReadinessError("gate fields do not match the closed contract")
            gate_id = gate["id"]
            if not isinstance(gate_id, str) or gate_id not in _GATES or gate_id in seen_gates:
                raise DeploymentReadinessError("gate identity is invalid")
            seen_gates.add(gate_id)
            if gate["status"] not in _STATUSES:
                raise DeploymentReadinessError("gate status is invalid")
            evidence = gate["evidence"]
            if not isinstance(evidence, list):
                raise DeploymentReadinessError("gate evidence must be an array")
            for evidence_path in evidence:
                _relative_evidence_path(evidence_path, root=root)
    if seen_editions != set(_EDITIONS):
        raise DeploymentReadinessError("readiness matrix must contain every edition")
    return top


def load_deployment_readiness_matrix(path: Path) -> DeploymentReadinessMatrix:
    """Read and verify one bounded local readiness matrix without external calls."""

    source_path = Path(path)
    root = source_path.resolve().parents[2]
    try:
        payload = read_yaml_document(source_path)
    except StructuredDocumentError as exc:
        raise DeploymentReadinessError(str(exc)) from exc
    verified = _verify_payload(payload, root=root)
    return DeploymentReadinessMatrix(payload=verified, source_path=source_path, root=root)


__all__ = ["DeploymentReadinessError", "DeploymentReadinessMatrix", "load_deployment_readiness_matrix"]
