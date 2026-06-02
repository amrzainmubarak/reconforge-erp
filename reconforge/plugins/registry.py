"""Plugin registry."""

from __future__ import annotations

from reconforge.plugins.base import ConnectorPlugin
from reconforge.plugins.generic_csv import GenericCSVConnector
from reconforge.plugins.odoo_export import OdooExportConnector
from reconforge.plugins.sap_export import SAPExportConnector


def list_connectors() -> list[str]:
    """Return registered connector names."""

    return ["generic_csv", "odoo_export", "sap_export"]


def get_connector(name: str) -> ConnectorPlugin:
    """Return a connector plugin by name."""

    normalized = name.lower().replace("-", "_")
    if normalized == "generic_csv":
        return GenericCSVConnector()
    if normalized == "odoo_export":
        return OdooExportConnector()
    if normalized == "sap_export":
        return SAPExportConnector()
    raise ValueError(f"Unsupported connector '{name}'. Supported connectors: {', '.join(list_connectors())}")
