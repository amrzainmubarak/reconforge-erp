"""Odoo export adapter foundation."""

from __future__ import annotations

from reconforge.connectors.manifest import ConnectorKind
from reconforge.plugins.generic_csv import GenericCSVConnector


class OdooExportConnector(GenericCSVConnector):
    """Read-only adapter for Odoo CSV/XLSX exports mapped outside ReconForge."""

    name = "odoo_export"
    manifest = GenericCSVConnector.manifest.model_copy(
        update={
            "connector_id": "odoo_export",
            "display_name": "Odoo local export profile",
            "kind": ConnectorKind.EXPORT_PROFILE,
        }
    )
