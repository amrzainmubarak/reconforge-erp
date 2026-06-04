# World-Class Platform Strategy

ReconForge ERP should grow into a world-class open-source platform for finance controls, ERP reconciliation, close management, audit evidence, and operational assurance. It should do that without becoming a SaaS clone, a direct ERP connector suite, a compliance certification tool, or an audit opinion system.

## Strategic Position

ReconForge is strongest when it helps users answer practical local questions:

- Do exported ERP transactions reconcile to the GL?
- Which exceptions are high risk?
- Which evidence exists locally?
- Which controls are represented by rule packs?
- What changed between periods?
- Which close tasks are blocked or incomplete?
- Which review items are prepared, reviewed, accepted risk, or still needing follow-up?

## Product Principles

- Local-first: core workflows read and write local files.
- Export-based: profiles describe ERP reports and mappings, not live connectors.
- Evidence-first: outputs should preserve source traceability and review metadata.
- Transparent: rules, risk scoring, and matching logic should be inspectable.
- Conservative: no legal, tax, regulatory, compliance, audit opinion, enterprise readiness, customer adoption, or vendor endorsement claims without proof.
- Modular: each feature should work as a small CLI/reporting module before becoming a Studio workflow.
- Tested: file handling, HTML rendering, YAML parsing, and malformed input paths need regression coverage.

## Strategic Wedges

- Consultant-led stock-to-GL and WIP cleanup.
- Local close checklist and readiness reporting.
- Rule-pack-derived control matrices.
- Evidence binder and client handoff workflows.
- Export profile validation for ERP implementation and reconciliation projects.
- Variance and recurring exception intelligence from generated outputs.

## What To Build Next

Prioritize modules that require no cloud service, no ERP credentials, and no multi-user security surface:

1. Close readiness score and calendar export.
2. Account reconciliation template from local summary/balance files.
3. Recurring exception aging and unresolved high-risk trend.
4. Control testing register from control matrix rows.
5. ERP profile confidence scoring.
6. Stronger evidence provenance plan.

## What To Avoid

- Direct ERP connector claims before implementation.
- Auth/RBAC bolted onto Studio without a security design.
- AI decisions that cannot be explained.
- Compliance framework claims that imply certification.
- Generated demo assets containing real financial data.
- Marketing language that implies customers, pilots, revenue, savings, or assurance.
