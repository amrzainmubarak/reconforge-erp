"""Backend-neutral conformance checks for manifest-driven connectors."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd

from reconforge.connectors.manifest import ConnectorCapability, ConnectorKind, ConnectorManifest
from reconforge.connectors.network import NetworkConnectorExecutor, NetworkConnectorRegistration


class ReadOnlyConnector(Protocol):
    manifest: ConnectorManifest

    def load_data(self, input_path: Path) -> dict[str, pd.DataFrame]: ...

    def validate_schema(self, datasets: dict[str, pd.DataFrame]) -> list[str]: ...


@dataclass(frozen=True)
class ConformanceResult:
    connector_id: str
    manifest_digest: str
    checks: tuple[str, ...]


def verify_manifest_portfolio(manifests: Iterable[ConnectorManifest]) -> tuple[str, ...]:
    """Validate the shared safety contract for a set of reference manifests.

    This is deliberately manifest-level evidence; connector transport and
    provider interoperability require their own runtime gates.
    """

    ordered = tuple(manifests)
    identifiers = [manifest.connector_id for manifest in ordered]
    if not ordered or len(set(identifiers)) != len(identifiers):
        raise ValueError("connector manifest identifiers must be non-empty and unique")
    for manifest in ordered:
        if manifest.capabilities != frozenset({ConnectorCapability.READ}):
            raise ValueError(f"{manifest.connector_id} is not read-only")
        if not manifest.synthetic_sandbox or not manifest.idempotent_reads:
            raise ValueError(f"{manifest.connector_id} lacks synthetic/idempotent read guarantees")
        if not manifest.schema_versions or not manifest.threat_model:
            raise ValueError(f"{manifest.connector_id} lacks schema/threat declarations")
        if manifest.kind is ConnectorKind.NETWORK_SOURCE:
            if not manifest.network_required or not manifest.egress_destinations:
                raise ValueError(f"{manifest.connector_id} lacks exact network egress")
            if manifest.authentication.value != "secret_reference":
                raise ValueError(f"{manifest.connector_id} lacks secret-reference authentication")
        elif manifest.network_required or manifest.egress_destinations:
            raise ValueError(f"{manifest.connector_id} has network fields without network kind")
    return tuple(sorted(identifiers))


def verify_read_only_connector(connector: ReadOnlyConnector, sandbox: Path) -> ConformanceResult:
    """Exercise the common local read boundary using caller-owned synthetic data."""

    manifest = connector.manifest
    if manifest.kind is ConnectorKind.NETWORK_SOURCE:
        raise ValueError("network connectors require the separate network sandbox conformance suite")
    if manifest.capabilities != frozenset({ConnectorCapability.READ}):
        raise ValueError("connector must be read-only")
    if not manifest.synthetic_sandbox:
        raise ValueError("connector does not declare synthetic sandbox support")
    before = sorted((path.relative_to(sandbox), path.read_bytes()) for path in sandbox.rglob("*") if path.is_file())
    datasets = connector.load_data(sandbox)
    messages = connector.validate_schema(datasets)
    after = sorted((path.relative_to(sandbox), path.read_bytes()) for path in sandbox.rglob("*") if path.is_file())
    if before != after:
        raise ValueError("connector mutated its input sandbox")
    if messages:
        raise ValueError("connector rejected the synthetic sandbox: " + "; ".join(messages))
    if not datasets:
        raise ValueError("connector returned no synthetic datasets")
    return ConformanceResult(
        connector_id=manifest.connector_id,
        manifest_digest=manifest.digest,
        checks=("manifest_valid", "read_only", "sandbox_unchanged", "schema_accepted", "datasets_present"),
    )


def verify_network_connector(
    registration: NetworkConnectorRegistration,
    executor: NetworkConnectorExecutor,
    *,
    idempotency_key: str,
    cursor: str | None = None,
) -> ConformanceResult:
    """Replay one synthetic read and require identical request and response identity."""

    manifest = registration.manifest
    if manifest.capabilities != frozenset({ConnectorCapability.READ}):
        raise ValueError("network connector must be read-only")
    if not manifest.synthetic_sandbox or not manifest.idempotent_reads:
        raise ValueError("network connector must declare synthetic sandbox and idempotent reads")
    first = executor.read(registration, idempotency_key=idempotency_key, cursor=cursor)
    replay = executor.read(registration, idempotency_key=idempotency_key, cursor=cursor)
    if (
        first.request_digest != replay.request_digest
        or first.response_digest != replay.response_digest
        or first.next_cursor != replay.next_cursor
    ):
        raise ValueError("network connector idempotent replay changed")
    return ConformanceResult(
        connector_id=manifest.connector_id,
        manifest_digest=manifest.digest,
        checks=(
            "manifest_valid",
            "read_only",
            "exact_https_egress",
            "secret_reference",
            "rate_limit_declared",
            "bounded_retry_declared",
            "cursor_contract",
            "idempotent_replay",
            "synthetic_sandbox",
        ),
    )
