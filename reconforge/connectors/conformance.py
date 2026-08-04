"""Backend-neutral conformance checks for manifest-driven connectors."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd

from reconforge.connectors.manifest import ConnectorCapability, ConnectorKind, ConnectorManifest
from reconforge.connectors.network import (
    ConnectorNetworkError,
    NetworkConnectorExecutor,
    NetworkConnectorRegistration,
    NetworkResponse,
    NetworkTransport,
)
from reconforge.connectors.writeback import WritebackIntent, WritebackPolicy
from reconforge.connectors.writeback_network import (
    WritebackNetworkExecutor,
    WritebackNetworkRegistration,
    WritebackNetworkResponse,
    WritebackNetworkTransport,
)


class ReadOnlyConnector(Protocol):
    manifest: ConnectorManifest

    def load_data(self, input_path: Path) -> dict[str, pd.DataFrame]: ...

    def validate_schema(self, datasets: dict[str, pd.DataFrame]) -> list[str]: ...


@dataclass(frozen=True)
class ConformanceResult:
    connector_id: str
    manifest_digest: str
    checks: tuple[str, ...]


@dataclass
class _FailureInjectionTransport:
    responses: list[NetworkResponse]
    calls: int = 0

    def get(
        self,
        endpoint: str,
        *,
        headers: dict[str, str],
        timeout_seconds: int,
        maximum_response_bytes: int,
    ) -> NetworkResponse:
        del endpoint, headers, timeout_seconds, maximum_response_bytes
        self.calls += 1
        if not self.responses:
            raise ConnectorNetworkError("connector_transport_failed")
        return self.responses.pop(0)


@dataclass
class _WritebackFailureInjectionTransport:
    responses: list[WritebackNetworkResponse]
    calls: int = 0

    def post(
        self,
        endpoint: str,
        *,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: int,
        maximum_response_bytes: int,
    ) -> WritebackNetworkResponse:
        del endpoint, headers, body, timeout_seconds, maximum_response_bytes
        self.calls += 1
        return self.responses.pop(0)


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
        if manifest.kind in {ConnectorKind.NETWORK_SOURCE, ConnectorKind.DATABASE_SOURCE}:
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


def verify_network_retry_failure_injection(
    registration: NetworkConnectorRegistration,
    executor_factory: Callable[[NetworkTransport], NetworkConnectorExecutor],
    *,
    transient_statuses: tuple[int, ...] = (503,),
    idempotency_key: str = "failure-injection-1",
    cursor: str | None = None,
) -> ConformanceResult:
    """Prove bounded transient retry behavior with a synthetic transport.

    The caller supplies the executor factory so credential resolution and
    timing remain explicit. No network is contacted and the synthetic
    response body is never interpreted as provider data. This is a runtime
    failure contract, not provider interoperability evidence.
    """

    if not transient_statuses or any(
        status not in {408, 425, 429} and not 500 <= status <= 599 for status in transient_statuses
    ):
        raise ValueError("transient_statuses must contain only retryable HTTP statuses")
    if len(transient_statuses) >= registration.manifest.retry_policy.maximum_attempts:
        raise ValueError("failure injection must leave one attempt for success")
    transport = _FailureInjectionTransport(
        [*(NetworkResponse(status, b"synthetic-transient") for status in transient_statuses), NetworkResponse(200, b"{}")]
    )
    result = executor_factory(transport).read(
        registration,
        idempotency_key=idempotency_key,
        cursor=cursor,
    )
    expected_attempts = len(transient_statuses) + 1
    if result.attempts != expected_attempts or transport.calls != expected_attempts:
        raise ValueError("network retry failure injection exceeded its declared bound")
    if b"synthetic-transient" in result.response_body:
        raise ValueError("transient failure body leaked into the successful response")
    return ConformanceResult(
        connector_id=registration.manifest.connector_id,
        manifest_digest=registration.manifest.digest,
        checks=(
            "manifest_valid",
            "synthetic_failure_injection",
            "bounded_transient_retry",
            "successful_recovery",
            "response_body_isolated",
        ),
    )


def verify_writeback_retry_failure_injection(
    registration: WritebackNetworkRegistration,
    executor_factory: Callable[[WritebackNetworkTransport], WritebackNetworkExecutor],
    intent: WritebackIntent,
    policy: WritebackPolicy,
    *,
    transient_statuses: tuple[int, ...] = (503,),
) -> ConformanceResult:
    """Prove bounded idempotent write-back retry with synthetic responses."""

    if not transient_statuses or any(
        status not in {408, 425, 429} and not 500 <= status <= 599 for status in transient_statuses
    ):
        raise ValueError("transient_statuses must contain only retryable HTTP statuses")
    if len(transient_statuses) >= registration.retry_policy.maximum_attempts:
        raise ValueError("failure injection must leave one attempt for success")
    response_fields = {
        "accepted": True,
        "idempotency_key": intent.idempotency_key,
        "provider_reference": "synthetic-provider-reference",
    }
    response_digest = hashlib.sha256(
        json.dumps(response_fields, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    response_body = json.dumps(
        {**response_fields, "response_digest": response_digest},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    transport = _WritebackFailureInjectionTransport(
        [*(WritebackNetworkResponse(status, b"synthetic-transient") for status in transient_statuses), WritebackNetworkResponse(200, response_body)]
    )
    result = executor_factory(transport).dispatch(intent, registration=registration, policy=policy)
    expected_attempts = len(transient_statuses) + 1
    if result.attempts != expected_attempts or transport.calls != expected_attempts:
        raise ValueError("write-back retry failure injection exceeded its declared bound")
    if result.intent.acknowledgement is None or result.intent.acknowledgement.idempotency_key != intent.idempotency_key:
        raise ValueError("write-back acknowledgement lost idempotency binding")
    return ConformanceResult(
        connector_id=registration.connector_id,
        manifest_digest=registration.digest,
        checks=(
            "registration_valid",
            "synthetic_failure_injection",
            "bounded_idempotent_retry",
            "successful_recovery",
            "acknowledgement_bound",
        ),
    )


def verify_writeback_compensation_retry_failure_injection(
    registration: WritebackNetworkRegistration,
    executor_factory: Callable[[WritebackNetworkTransport], WritebackNetworkExecutor],
    intent: WritebackIntent,
    policy: WritebackPolicy,
    *,
    payload: bytes,
    payload_digest: str,
    transient_statuses: tuple[int, ...] = (503,),
) -> ConformanceResult:
    """Prove bounded retry and acknowledgement binding for compensation.

    The transport is entirely synthetic. The compensation payload and digest
    are supplied by the caller so this check cannot silently reuse the original
    write-back payload or introduce provider-specific semantics.
    """

    if not transient_statuses or any(
        status not in {408, 425, 429} and not 500 <= status <= 599 for status in transient_statuses
    ):
        raise ValueError("transient_statuses must contain only retryable HTTP statuses")
    if len(transient_statuses) >= registration.retry_policy.maximum_attempts:
        raise ValueError("failure injection must leave one attempt for success")
    compensation_key = intent.idempotency_key + ":compensation"
    response_fields = {
        "accepted": True,
        "idempotency_key": compensation_key,
        "provider_reference": "synthetic-compensation-reference",
    }
    response_digest = hashlib.sha256(
        json.dumps(response_fields, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    response_body = json.dumps(
        {**response_fields, "response_digest": response_digest},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    transport = _WritebackFailureInjectionTransport(
        [
            *(WritebackNetworkResponse(status, b"synthetic-transient") for status in transient_statuses),
            WritebackNetworkResponse(200, response_body),
        ]
    )
    result = executor_factory(transport).dispatch_compensation(
        intent,
        registration=registration,
        policy=policy,
        payload=payload,
        payload_digest=payload_digest,
    )
    expected_attempts = len(transient_statuses) + 1
    if result.attempts != expected_attempts or transport.calls != expected_attempts:
        raise ValueError("write-back compensation retry failure injection exceeded its declared bound")
    if result.intent.status.value != "compensated":
        raise ValueError("write-back compensation did not reach the compensated state")
    if result.intent.acknowledgement is None or result.intent.acknowledgement.idempotency_key != compensation_key:
        raise ValueError("write-back compensation acknowledgement lost idempotency binding")
    return ConformanceResult(
        connector_id=registration.connector_id,
        manifest_digest=registration.digest,
        checks=(
            "registration_valid",
            "synthetic_failure_injection",
            "bounded_compensation_retry",
            "successful_compensation",
            "compensation_acknowledgement_bound",
        ),
    )
