# ERP vision: gap and comparison scorecard — 2026-10-28

Source baseline: `b1ae1b5e7aad0cc9893bfda65ff44b422aaa279b`. This is a
discovery scorecard, not a product ranking or a test of competitors. Vendor
descriptions were consulted on 2026-10-28; specific editions, versions,
availability, prices and total cost are unknown unless separately measured.

| Reference | Vendor-described scope and deployment | Source |
| --- | --- | --- |
| SAP S/4HANA | Public, private and customer-operated offerings have different deployment and operations models. | [SAP offering comparison](https://help.sap.com/docs/SAP_S4HANA_CLOUD_PE/b89b8b9026e1456bb2a1df7c0d59c937/1485d139460246d2a4b936c0bb0ca272.html) |
| Oracle Fusion Cloud ERP | Cloud ERP and financial management; edition and scenario performance unknown. | [Oracle ERP](https://www.oracle.com/erp/) |
| Microsoft Dynamics 365 | Finance and supply-chain applications; exact deployment and edition for a comparison unknown. | [Microsoft Dynamics 365](https://www.microsoft.com/en-us/dynamics-365/products/finance) |
| NetSuite | Cloud financial management describes links to order management, inventory and CRM. | [NetSuite financial management](https://www.netsuite.com/portal/products/erp/financial-management.shtml) |
| Odoo | Integrated business applications; version, licensing and deployment for a comparison unknown. | [Odoo applications](https://www.odoo.com/app) |
| ERPNext | Documentation lists accounting, HR, CRM, manufacturing, order and asset management; it identifies GPLv3. | [ERPNext documentation](https://docs.erpnext.com/index) |
| IFS Cloud | Vendor describes ERP, asset and field-service management. | [IFS products](https://www.ifs.com/en/about/trust-center/products) |
| BlackLine | Vendor describes financial close, account reconciliation and transaction matching. | [BlackLine financial close](https://www.blackline.com/products/financial-close/) |
| FloQast | Vendor describes reconciliation support, ownership, review and sign-off. | [FloQast reconciliations](https://www.floqast.com/uk/close-management/products/account-reconciliations) |

## ReconForge qualification gaps

| Scenario | Source evidence and missing end-to-end proof | Status |
| --- | --- | --- |
| Lead to cash | Partial stock-to-cash evidence exists; authoritative CRM origin, complete reporting and browser chain remain unqualified. | blocked |
| Demand to production and GL | Separate supply and production evidence; one receipt-to-FIFO-to-WIP-to-quality genealogy and oracle absent. | blocked |
| Employee to payroll and GL | Components exist; connected attendance/leave, payroll and employee-report oracle absent. | blocked |
| Contract to project profitability | Components exist; original contract, resource, time, milestone and posted profitability chain unproved. | blocked |
| Intercompany to group statements | Components exist; one paired source, settlement, FX, elimination and reconciled statement chain unproved. | blocked |
| Bank to evidence and period close | Legacy replay and context-sensitive grouped matching remain open; full controlled close/reopen needs independent qualification. | blocked |
| Asset and retail journeys | Partial evidence exists; complete source-to-report, failure and restore qualification not established here. | blocked |

See `ENTERPRISE_CYCLES_2026-10-26.md` for historical source and detailed
limitations. No new full-cycle execution or competitor test is represented here.

## Measurement protocol

For each persona, sector and organization size, define the same synthetic,
versioned input and expected source-to-outcome chain, record dataset checksum,
product version, edition, configuration, environment, denominator, repetitions
and failures. Measure correctness, task completion/time/errors, accessibility
and language, isolation/SoD, import lineage, offline operation, recovery,
resource use, installation/upgrade, integration, documented ownership and total
cost only where comparable evidence exists. Record vendor claims, our observed
results and independent reviews separately. Acceptance thresholds require real
user and operating context; unknown values remain unknown. No score or global
ranking is assigned until comparable trials and independent evidence exist.
