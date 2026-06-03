---
name: ERP mapping profile
about: Propose or improve an export-based ERP mapping profile
title: "[Mapping]: "
labels: "erp-profile"
assignees: ""
---

## ERP Source

Name the ERP and export/report source, such as Odoo stock valuation layers, SAP MB51, SAP FAGLL03, ERPNext stock ledger, NetSuite saved search, or Dynamics export.

## Workflow

What reconciliation or audit workflow should this mapping support?

## Export Files

List the exported files and whether they are CSV or XLSX.

## Sanitized Field Headers

Paste sanitized column headers only. Do not include live customer, supplier, employee, invoice, GL, asset, work-order, or amount data.

## Canonical ReconForge Files

Which canonical files should this map to?

- `stock_moves.csv`
- `gl_entries.csv`
- `work_orders.csv`
- `purchase_orders.csv`
- `products.csv`
- `customers.csv`
- `old_parts_returns.csv`
- `invoices.csv`

## Acceptance Criteria

How should maintainers know the mapping profile works?

## Claim Boundaries

This request is for export-based profiles only. Do not claim direct ERP connectors, official vendor certification, or live ERP sync.
