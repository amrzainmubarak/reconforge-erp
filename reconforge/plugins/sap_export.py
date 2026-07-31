"""SAP export adapter foundation."""

from __future__ import annotations

from reconforge.connectors.manifest import ConnectorKind
from reconforge.plugins.generic_csv import GenericCSVConnector


class SAPExportConnector(GenericCSVConnector):
    """Read-only adapter for SAP MB51/FAGLL03/FBL3N-style exports."""

    name = "sap_export"
    manifest = GenericCSVConnector.manifest.model_copy(
        update={
            "connector_id": "sap_export",
            "display_name": "SAP local export profile",
            "kind": ConnectorKind.EXPORT_PROFILE,
        }
    )
