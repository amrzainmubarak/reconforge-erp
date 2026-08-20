from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError

from reconforge.connectors import (
    BANK_STATEMENT_CAMT053_MANIFEST,
    DATABASE_REFERENCE_MANIFEST,
    ERP_NEXT_MANIFEST,
    ERP_NEXT_PAYMENT_ENTRY_MANIFEST,
    ERP_REFERENCE_MANIFEST,
    OBJECT_REFERENCE_MANIFEST,
    PAYMENT_STATEMENT_MANIFEST,
    REFERENCE_REST_MANIFEST,
    SFTP_REFERENCE_MANIFEST,
    WORLD_BANK_PUBLIC_MANIFEST,
)
from reconforge.connectors.bank_statement_camt053 import bank_statement_camt053_registration
from reconforge.connectors.conformance import (
    build_manifest_portfolio_report,
    verify_manifest_portfolio,
    verify_network_connector,
    verify_network_retry_failure_injection,
    verify_read_only_connector,
)
from reconforge.connectors.erpnext_payment_reference import erpnext_payment_entry_registration
from reconforge.connectors.erpnext_reference import erpnext_registration
from reconforge.connectors.manifest import ConnectorCapability
from reconforge.connectors.network import NetworkConnectorExecutor, NetworkConnectorRegistration, NetworkResponse
from reconforge.plugins.registry import get_connector, list_connectors


@dataclass
class _PortfolioSecrets:
    def resolve(self, reference: str) -> bytes:
        assert reference == "vault://synthetic/connector"
        return b"synthetic-connector-secret"


@dataclass
class _PortfolioTransport:
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
        return NetworkResponse(status=200, body=b"{}")


def test_builtin_registry_is_static_allowlist_with_truthful_kinds() -> None:
    assert list_connectors() == ["generic_csv", "odoo_export", "sap_export"]
    assert get_connector("generic_csv").manifest.kind == "local_file"
    assert get_connector("odoo_export").manifest.kind == "export_profile"
    assert get_connector("sap_export").manifest.kind == "export_profile"
    with pytest.raises(ValueError, match="Unsupported connector"):
        get_connector("../../arbitrary_module")


@pytest.mark.parametrize("connector_id", ["generic_csv", "odoo_export", "sap_export"])
def test_builtin_read_only_connector_conformance(tmp_path: Path, connector_id: str) -> None:
    (tmp_path / "synthetic.csv").write_text("reference,amount\nA-1,10.00\n", encoding="utf-8")
    connector = get_connector(connector_id)
    result = verify_read_only_connector(connector, tmp_path)
    assert result.connector_id == connector_id
    assert result.checks == (
        "manifest_valid",
        "read_only",
        "sandbox_unchanged",
        "schema_accepted",
        "datasets_present",
    )
    assert len(result.manifest_digest) == 64


def test_manifest_digest_is_deterministic_and_sensitive() -> None:
    manifest = get_connector("generic_csv").manifest
    assert manifest.digest == manifest.digest
    changed = manifest.model_copy(update={"version": "1.0.1"})
    assert changed.digest != manifest.digest


def test_reference_manifest_portfolio_is_read_only_and_governed() -> None:
    assert verify_manifest_portfolio(
        (
            REFERENCE_REST_MANIFEST,
            SFTP_REFERENCE_MANIFEST,
            OBJECT_REFERENCE_MANIFEST,
            DATABASE_REFERENCE_MANIFEST,
            PAYMENT_STATEMENT_MANIFEST,
            ERP_REFERENCE_MANIFEST,
            WORLD_BANK_PUBLIC_MANIFEST,
            BANK_STATEMENT_CAMT053_MANIFEST,
            ERP_NEXT_MANIFEST,
            ERP_NEXT_PAYMENT_ENTRY_MANIFEST,
        )
    ) == (
        "bank-statement-camt053-readonly",
        "erpnext-gl-entry-readonly",
        "erpnext-payment-entry-readonly",
        "reference-database-readonly",
        "reference-erp-readonly",
        "reference-object-storage-readonly",
        "reference-payment-statement-readonly",
        "reference-rest-readonly",
        "reference-sftp-readonly",
        "world-bank-public-readonly",
    )


def test_reference_manifest_portfolio_report_is_order_invariant_and_digest_bound() -> None:
    manifests = (
        REFERENCE_REST_MANIFEST,
        SFTP_REFERENCE_MANIFEST,
        OBJECT_REFERENCE_MANIFEST,
        DATABASE_REFERENCE_MANIFEST,
        PAYMENT_STATEMENT_MANIFEST,
        ERP_REFERENCE_MANIFEST,
        WORLD_BANK_PUBLIC_MANIFEST,
        BANK_STATEMENT_CAMT053_MANIFEST,
        ERP_NEXT_MANIFEST,
        ERP_NEXT_PAYMENT_ENTRY_MANIFEST,
    )
    first = build_manifest_portfolio_report(manifests)
    shuffled = build_manifest_portfolio_report(tuple(reversed(manifests)))
    assert first == shuffled
    assert len(first.portfolio_digest) == 64
    changed = build_manifest_portfolio_report(
        (*manifests[:-1], ERP_NEXT_PAYMENT_ENTRY_MANIFEST.model_copy(update={"version": "1.0.1"}))
    )
    assert changed.connector_ids == first.connector_ids
    assert changed.portfolio_digest != first.portfolio_digest


@pytest.mark.parametrize(
    ("registration_factory", "cursor"),
    [
        (bank_statement_camt053_registration, None),
        (erpnext_registration, "7"),
        (erpnext_payment_entry_registration, "7"),
    ],
)
def test_provider_network_manifest_portfolio_replays_through_common_conformance(
    registration_factory: Callable[..., NetworkConnectorRegistration], cursor: str | None
) -> None:
    transport = _PortfolioTransport()
    registration = registration_factory(credential_reference="vault://synthetic/connector")
    result = verify_network_connector(
        registration,
        NetworkConnectorExecutor(transport, secret_resolver=_PortfolioSecrets()),
        idempotency_key="portfolio-replay-1",
        cursor=cursor,
    )

    assert result.connector_id in {
        "bank-statement-camt053-readonly",
        "erpnext-gl-entry-readonly",
        "erpnext-payment-entry-readonly",
    }
    assert result.checks == (
        "manifest_valid",
        "read_only",
        "exact_https_egress",
        "secret_reference",
        "rate_limit_declared",
        "bounded_retry_declared",
        "cursor_contract",
        "idempotent_replay",
        "synthetic_sandbox",
    )
    assert transport.calls == 2

    retry_result = verify_network_retry_failure_injection(
        registration,
        lambda retry_transport: NetworkConnectorExecutor(retry_transport, secret_resolver=_PortfolioSecrets()),
        transient_statuses=(503, 429),
    )
    assert retry_result.checks == (
        "manifest_valid",
        "synthetic_failure_injection",
        "bounded_transient_retry",
        "successful_recovery",
        "response_body_isolated",
    )


def test_manifest_v1_rejects_write_capability() -> None:
    manifest = get_connector("generic_csv").manifest
    with pytest.raises(ValidationError, match="write capability is not supported"):
        manifest.__class__.model_validate(
            {**manifest.model_dump(), "capabilities": [ConnectorCapability.READ, ConnectorCapability.WRITE]}
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"authentication": "secret_reference"}, "local connectors cannot request authentication"),
        ({"egress_destinations": ["api.example.test"]}, "network_required must exactly match"),
        ({"version": "latest"}, "version must be semantic version"),
        ({"synthetic_sandbox": False}, "synthetic sandbox support"),
    ],
)
def test_manifest_and_conformance_fail_closed(tmp_path: Path, changes: dict[str, object], message: str) -> None:
    connector = get_connector("generic_csv")
    if "synthetic_sandbox" in changes:
        connector.manifest = connector.manifest.model_copy(update=changes)
        with pytest.raises(ValueError, match=message):
            verify_read_only_connector(connector, tmp_path)
        return
    with pytest.raises(ValidationError, match=message):
        connector.manifest.__class__.model_validate({**connector.manifest.model_dump(), **changes})
