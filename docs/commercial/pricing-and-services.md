# Pricing And Services

This document is a preliminary future service model for ReconForge ERP. It is not a claim of current customer adoption, revenue, guarantees, or certified audit delivery. Pricing ranges are hypotheses for positioning and should be validated through real discovery calls.

## Ethical Boundaries

- No fake guarantees.
- No claim of financial savings without client-validated evidence.
- No access to live ERP systems unless separately contracted and scoped.
- No financial audit opinion unless delivered by a qualified auditor under an appropriate engagement.
- Clients must validate outputs, mappings, assumptions, and exceptions.
- ReconForge core workflows are export-based unless a future connector is explicitly implemented.

## 1. ERP Reconciliation Health Check

- Target customer: finance controllers, internal audit teams, workshop/fleet operators, and ERP consultants needing a focused local review.
- Deliverables: validated export checklist, management pack, executive report, evidence binder, review register, client handoff pack, findings walkthrough.
- Timeline: 1 to 2 weeks after usable exports are provided.
- Required data: stock movements, GL entries, work orders, purchase orders, invoices, old-part returns where applicable.
- Output artifacts: `management_pack.xlsx`, `executive_report.html`, `evidence/`, `review_register.xlsx`, `client_pack/`.
- Buyer value: quickly surfaces reconciliation and operational-control gaps without a long software rollout.
- Pricing hypothesis: preliminary fixed fee, USD 2,500 to 7,500 depending on scope and data readiness.
- Included: export review, local run, exception walkthrough, recommendations.
- Not included: audit opinion, remediation execution, live ERP integration, recurring monitoring.

## 2. Monthly Reconciliation Service

- Target customer: companies that want repeatable monthly exception review from exported ERP data.
- Deliverables: monthly management pack, period comparison, review register, recurring exception list, handoff call.
- Timeline: monthly cycle, typically 2 to 5 business days after export receipt.
- Required data: current-period exports and prior-period ReconForge output folders.
- Output artifacts: monthly reports, `period_comparison.xlsx`, `period_comparison.html`, evidence updates.
- Buyer value: helps teams see whether exceptions are improving, recurring, or newly introduced.
- Pricing hypothesis: preliminary monthly retainer, USD 1,500 to 6,000 depending on volume and meeting cadence.
- Included: local processing, comparison, recurring findings summary, review call.
- Not included: guaranteed issue resolution, audit sign-off, ERP configuration changes.

## 3. Odoo/SAP Export Mapping Setup

- Target customer: Odoo implementers, SAP users, ERP consultants, and finance teams adapting exports.
- Deliverables: mapping inspection report, export template checklist, validated mapping pack notes, sample run.
- Timeline: 3 to 10 business days depending on export complexity.
- Required data: sample CSV/XLSX exports, ERP layout descriptions, period/company scope.
- Output artifacts: `mapping_report.md`, `mapping_report.json`, mapping notes, validation output.
- Buyer value: reduces friction when converting ERP exports into ReconForge canonical files.
- Pricing hypothesis: preliminary fixed fee, USD 1,500 to 5,000.
- Included: header inspection, gap list, suggested mappings, validation support.
- Not included: direct ERP connector, custom ETL platform, guaranteed semantic correctness without client validation.

## 4. Consultant Toolkit Training

- Target customer: independent ERP consultants, audit consultants, and finance transformation teams.
- Deliverables: training session, demo script, control-pack walkthrough, mapping workflow, review workflow practice.
- Timeline: half-day to two-day workshop.
- Required data: sample data or sanitized client exports.
- Output artifacts: training deck, command checklist, demo outputs, practice review register.
- Buyer value: enables consultants to run local demos and pilot checks consistently.
- Pricing hypothesis: preliminary USD 750 to 3,500 per workshop depending on length and customization.
- Included: guided setup, demo workflow, common troubleshooting, local-first safety practices.
- Not included: client-specific remediation, custom control-pack development unless separately scoped.

## 5. Self-Hosted Support Package

- Target customer: teams running ReconForge locally in a controlled environment.
- Deliverables: installation support, Docker/local deployment checklist, upgrade guidance, support hours.
- Timeline: monthly or quarterly support arrangement.
- Required data: environment details, permitted local paths, export workflow, support contact.
- Output artifacts: deployment notes, support log, verification checklist.
- Buyer value: gives organizations confidence running a local open-source workflow.
- Pricing hypothesis: preliminary USD 500 to 4,000 per month based on support level.
- Included: setup assistance, troubleshooting, release guidance, Docker command verification where available.
- Not included: hosted SaaS, managed infrastructure, security certification, enterprise SSO.

## 6. Custom Control Pack Development

- Target customer: companies or consultants needing domain-specific checks.
- Deliverables: YAML control pack, mapping notes, expected exceptions, tests, sample command, documentation.
- Timeline: 1 to 4 weeks depending on complexity.
- Required data: control objective, sample exports, business rules, reviewer acceptance criteria.
- Output artifacts: `pack.yml`, `rules.yml`, `mapping.yml`, `risk_model.yml`, README, tests.
- Buyer value: converts repeatable manual control checks into versioned local rules.
- Pricing hypothesis: preliminary USD 2,000 to 15,000 depending on rules, data sources, and testing depth.
- Included: rule design, implementation, local validation, documentation.
- Not included: legal/audit opinion, live ERP changes, guarantee of all possible exception detection.

## Packaging Notes

Service delivery should use careful language:

- "local health check" instead of "certified audit"
- "exception indicators" instead of "proven fraud"
- "estimated value impact" instead of "savings"
- "export-based Odoo/SAP workflow" instead of "native ERP integration"
- "pilot-ready" instead of "enterprise production adopted"
