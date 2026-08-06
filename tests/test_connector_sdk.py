from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from reconforge.connectors import (
    DATABASE_REFERENCE_MANIFEST,
    ERP_REFERENCE_MANIFEST,
    OBJECT_REFERENCE_MANIFEST,
    PAYMENT_STATEMENT_MANIFEST,
    REFERENCE_REST_MANIFEST,
    SFTP_REFERENCE_MANIFEST,
    WORLD_BANK_PUBLIC_MANIFEST,
)
from reconforge.connectors.conformance import verify_manifest_portfolio, verify_read_only_connector
from reconforge.connectors.manifest import ConnectorCapability
from reconforge.plugins.registry import get_connector, list_connectors


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
        )
    ) == (
        "reference-database-readonly",
        "reference-erp-readonly",
        "reference-object-storage-readonly",
        "reference-payment-statement-readonly",
        "reference-rest-readonly",
        "reference-sftp-readonly",
        "world-bank-public-readonly",
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
