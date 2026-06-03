# NetSuite Inventory vs GL Control Pack

This pack supports local, export-based review of NetSuite inventory activity and GL impact/accounting-line exports mapped into ReconForge canonical files. It is not a direct NetSuite connector and does not require cloud upload.

## Required Exports

- Inventory Activity or inventory transaction saved search.
- Transaction Accounting Lines, GL Impact, or equivalent accounting-line export.
- Item saved search for item master validation.

## Limitations

- Export-based only; no direct NetSuite API connector is implemented.
- Users must validate subsidiary, location, account, and accounting period scope.
- ReconForge does not provide an audit opinion or compliance certification.
