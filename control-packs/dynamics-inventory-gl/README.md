# Microsoft Dynamics Inventory vs GL Control Pack

This pack supports local, export-based review of Microsoft Dynamics inventory transaction and general ledger exports mapped into ReconForge canonical files. It is not a direct Dynamics connector and does not require cloud upload.

## Required Exports

- Inventory transactions or posted inventory transaction export.
- General ledger transactions or voucher transaction export.
- Released products or item master export.

## Limitations

- Export-based only; no direct Microsoft Dynamics API connector is implemented.
- Users must validate legal entity, fiscal period, site, warehouse, and ledger account scope.
- ReconForge does not provide legal, tax, audit, or regulatory certification.
