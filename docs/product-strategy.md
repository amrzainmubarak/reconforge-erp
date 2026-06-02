# Product Strategy

## Product Vision

ReconForge ERP is an open-source ERP reconciliation and audit intelligence platform that helps companies reconcile stock movements, GL entries, work orders, WIP, invoices, purchase flows, and operational controls from Odoo, SAP exports, and generic ERP data locally, safely, and auditably.

The long-term vision is to make inventory-to-finance reconciliation as repeatable and inspectable as software testing.

## Product Category

ReconForge ERP belongs in a focused category: ERP reconciliation and audit intelligence. It is adjacent to financial close software, transaction matching, data-quality tooling, and GRC evidence workflows, but its center is the operational accounting boundary between stores, workshops, production, WIP, invoicing, and GL.

## Ideal Customer Profiles

- ERP consultants validating accounting and inventory flows during implementation.
- Odoo implementers who need repeatable export-based control checks.
- SAP users reconciling MB51 material movements with FAGLL03/FBL3N line items.
- Finance controllers preparing month-end inventory and WIP review packs.
- Internal auditors testing source-document traceability.
- External auditors requesting evidence for stock consumption and WIP balances.
- Workshop, service-center, fleet, dealership, and manufacturing teams that consume spare parts against work orders.

## Primary Use Cases

- Compare stock movements to GL postings.
- Detect stock movements without financial impact.
- Detect GL expenses without source stock movement.
- Review WIP aging and stale open work orders.
- Detect direct purchase-and-fit transactions that bypass stores.
- Check old-part return policy compliance.
- Produce audit evidence folders for high-risk exceptions.

## Secondary Use Cases

- Validate ERP export structure before reconciliation.
- Generate anonymized demo datasets while preserving matching relationships.
- Benchmark reconciliation performance before larger deployments.
- Create industry-specific rule packs for workshops, fleets, manufacturing, and dealership service teams.

## Differentiation

ReconForge ERP is practical where spreadsheets are flexible but fragile and enterprise SaaS is mature but expensive. It combines domain-specific controls, local execution, explainable matching, YAML rule packs, synthetic data generation, and audit binder outputs.

## Why Open Source Matters

Accounting controls should be inspectable. Open source lets auditors, consultants, and finance teams understand how exceptions are generated, challenge the logic, improve rule packs, and run sensitive data locally.

## Why Local-First Matters

ERP exports often contain customer, supplier, employee, asset, pricing, and invoice information. A local-first posture reduces security review friction and allows teams to start with a safe proof of value before considering hosted workflows.

## Why ERP-Export Workflows Matter

Many real control reviews begin with exported CSV or Excel files because ERP customization, permissions, integrations, and audit independence make direct database access difficult. ReconForge ERP treats exports as first-class inputs rather than a temporary workaround.

## Commercial Path

ReconForge ERP can remain a useful open-source core while supporting commercial work later:

- Implementation services for mapping customer ERP exports.
- Paid support for finance and audit teams.
- Self-hosted Pro edition with review workflow, saved rule packs, access controls, and evidence attachments.
- Future SaaS for teams that want hosted collaboration after anonymization and security review.

## GitHub Growth Strategy

- Keep sample data realistic and safe.
- Publish clear playbooks for finance controllers, Odoo consultants, SAP users, auditors, warehouse managers, and workshop managers.
- Use issues to invite concrete packs: SAP template mapping, Odoo valuation, ERPNext, NetSuite, manufacturing WIP, fleet maintenance.
- Maintain a clean demo workflow that produces reports in minutes.
- Avoid inflated claims; credibility comes from working code, examples, and documentation.

## Community Strategy

- Welcome ERP consultants, accountants, auditors, and developers equally.
- Separate domain discussions from implementation issues where useful.
- Encourage anonymized sample exports and mapping suggestions.
- Use control-pack contributions as the easiest path for non-core developers.

## 90-Day Roadmap

- Improve rule-pack coverage from community feedback.
- Add mapper templates for common Odoo and SAP export column names.
- Add reviewer fields to evidence summaries.
- Publish sample screenshots generated from local reports.
- Improve benchmark coverage for 10k, 100k, and 1m row synthetic datasets.

## 12-Month Roadmap

- Native Odoo connector or guided export assistant.
- SAP export mapping profiles for MB51, FAGLL03, FBL3N, and PM/CS work orders.
- Exception review workflow in ReconForge Studio.
- Multi-company and multi-period comparison.
- Connector SDK for ERPNext, NetSuite, and custom ERP systems.
- Optional packaged desktop distribution for non-technical users.

## Open-Core Commercial Model

The open-source core should remain capable: CLI, validation, reconciliation, rule packs, anonymizer, synthetic data, benchmark, reports, and evidence binder. Commercial additions can focus on collaboration, governance, enterprise deployment, reviewer workflows, connector management, scheduled jobs, and support.

## Consulting Services Model

Consulting can include export mapping, control-pack customization, month-end close design, audit support, Odoo/SAP implementation validation, and workshop inventory control diagnostics.

## Self-Hosted Pro Model

A self-hosted Pro edition could add user management, evidence attachments, exception assignment, approval workflow, saved periods, role-specific dashboards, and enterprise support while keeping data inside the customer environment.

## SaaS Future Model

A hosted SaaS version should be considered only after security, anonymization, and customer trust foundations are strong. Its value would be collaboration, recurring close workflows, managed rule packs, and benchmarking across periods, not replacing the open-source local engine.
