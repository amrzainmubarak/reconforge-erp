"""Odoo export adapter foundation."""

from __future__ import annotations

from reconforge.plugins.generic_csv import GenericCSVConnector


class OdooExportConnector(GenericCSVConnector):
    """Read-only adapter for Odoo CSV/XLSX exports mapped outside ReconForge."""

    name = "odoo_export"
