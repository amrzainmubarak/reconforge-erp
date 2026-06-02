"""SAP export adapter foundation."""

from __future__ import annotations

from reconforge.plugins.generic_csv import GenericCSVConnector


class SAPExportConnector(GenericCSVConnector):
    """Read-only adapter for SAP MB51/FAGLL03/FBL3N-style exports."""

    name = "sap_export"
