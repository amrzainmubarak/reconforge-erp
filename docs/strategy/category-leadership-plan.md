# Category Leadership Plan

## 1. Category Name

Local-first ERP Audit Intelligence.

## 2. Category Definition

Local-first ERP Audit Intelligence is software that inspects ERP exports on a user's own machine or self-hosted environment, applies deterministic financial and operational controls, reconciles ERP operations to accounting records, and produces audit-ready evidence without requiring cloud upload.

## 3. Why This Category Matters

ERP systems record operations and accounting, but many close and audit workflows still depend on exported spreadsheets. The highest-risk gaps often sit between modules: stock movements versus GL entries, WIP versus work orders, purchase fitting versus invoices, and operational documents versus accounting postings. These checks need to be repeatable, explainable, and safe for sensitive ERP data.

## 4. Why Current Tools Leave A Gap

Enterprise close platforms are powerful but expensive, cloud-oriented, and implementation-heavy. ERP systems are authoritative but system-specific and often inaccessible to auditors or consultants. Open-source data tools are flexible but generic. Excel is familiar but fragile and difficult to audit. The gap is a practical local tool that speaks ERP, inventory, accounting, WIP, and audit evidence language.

## 5. ReconForge's Unique Angle

ReconForge is the open-source audit intelligence layer between ERP operations and financial accounting. Its angle is:

- Local-first processing.
- Export-based workflows.
- Deterministic reconciliation and rules.
- YAML control packs.
- Evidence binder outputs.
- Local anonymization as a reviewed risk-reduction aid, not a safe-sharing guarantee.
- Consultant-friendly mapping profiles.

## 6. Beachhead Market

Odoo/SAP export-based stock-to-GL, WIP, and work-order reconciliation for mid-market companies, ERP consultants, auditors, inventory teams, workshop managers, and finance controllers.

## 7. Expansion Markets

1. ERPNext export reconciliation.
2. Microsoft Dynamics CSV/export reconciliation.
3. NetSuite saved-search reconciliation.
4. SAP Business One export reconciliation.
5. Manufacturing variance review.
6. Multi-warehouse inventory controls.
7. Purchase-to-pay audit evidence.
8. Fleet and workshop control packs.

## 8. Open-Source Wedge

The wedge is a useful free core that can be installed, run against sample exports, and extended through rule packs without asking for cloud credentials or customer data. Contributors can add mappings, rules, examples, and tests without needing access to private ERP systems.

## 9. Technical Moat

1. Canonical ERP audit schemas.
2. Validated control-pack format.
3. Deterministic matching strategies.
4. Cross-file rule operators.
5. Evidence binder format.
6. Benchmark datasets and performance results.
7. Local review state and multi-period exception tracking.
8. Plugin interface for export adapters.

## 10. Trust Moat

1. No cloud upload by default.
2. No fake adoption claims.
3. Transparent control logic.
4. Tests for serious features.
5. Security workflows in CI.
6. Anonymization workflow.
7. Clear unsupported-claims policy.

## 11. Community Moat

1. Odoo consultants can contribute mapping improvements.
2. SAP consultants can contribute export field profiles.
3. Auditors can contribute control language and expected exceptions.
4. Finance users can contribute anonymized scenarios.
5. Engineers can improve CLI, Studio, schemas, and tests.

## 12. Documentation Moat

Documentation should become a differentiator by being practical, not promotional:

- Export guides.
- Mapping profiles.
- Rule-pack schema reference.
- Control-pack authoring examples.
- Playbooks by persona.
- Evidence binder interpretation.
- Pilot implementation guides.

## 13. Data Safety Moat

ReconForge should make data safety part of the product, not a disclaimer:

- Local processing.
- Anonymizer before sharing.
- Synthetic demo data.
- No API keys required for core workflows.
- Explicit guidance for generated reports and evidence folders.
- Secure download route patterns for Studio.

## 14. Consultant Ecosystem Moat

Consultants need repeatable client delivery. ReconForge should provide:

- Mapping wizard.
- Client data intake checklist.
- Anonymized demo package generator.
- Branded report outputs.
- Handoff pack.
- Implementation playbooks.
- Training and certification later.

## 15. Commercialization Path

Keep the open-source core strong. Monetize around services, support, self-hosted collaboration, branded handoff packs, implementation accelerators, managed audit packs, and training. SaaS can come later after the self-hosted local model is mature.

## 16. 30-Day Plan

1. Publish rule-pack schema reference.
2. Improve Odoo and SAP mapping profiles.
3. Add tests for profile structure.
4. Add README/changelog v0.4.0 positioning.
5. Add issue templates for mapping and control packs.
6. Draft adoption and commercial strategy docs.
7. Create first good-first issue backlog manually in GitHub.

## 17. 90-Day Plan

1. Build a mapping validation command.
2. Add Odoo demo workflow with realistic sample exports.
3. Add SAP demo workflow with realistic sample exports.
4. Add evidence reviewer status workflow.
5. Add Studio filters and reviewer notes.
6. Publish 10k benchmark dataset and report.
7. Recruit first external contributors around control packs and mappings.

## 18. 180-Day Plan

1. Add multi-period comparison.
2. Add recurring/new/resolved exception reporting.
3. Add close pack output.
4. Add ERPNext/Dynamics/NetSuite CSV profiles.
5. Add mapping wizard foundation.
6. Add consultant implementation playbooks.
7. Execute, independently verify, and retain one signed release with every exact-subject SBOM.

## 19. 12-Month Plan

1. Stabilize CLI, schemas, control packs, and evidence binder format.
2. Release v1.0.0 stable open-source core.
3. Launch self-hosted review platform foundation.
4. Establish governance for official and community packs.
5. Run real pilots with documented outcomes, without inventing logos or testimonials.
6. Create training materials and partner program foundations.

## 20. What Success Looks Like

1. Users can run Odoo/SAP export workflows without private support.
2. Contributors can add a mapping profile or rule pack safely.
3. Benchmarks are reproducible.
4. Evidence packs are trusted by finance and audit reviewers.
5. Real users report issues from real export workflows.
6. Commercial pilots are based on clear scope and honest capabilities.

## 21. What Failure Looks Like

1. The project becomes a broad generic accounting tool.
2. Claims outpace implementation.
3. Mapping stays informal and unvalidated.
4. Community cannot tell where to contribute.
5. Commercial work takes priority over open-source core trust.
6. Data safety posture weakens.

## 22. Metrics To Track Weekly

1. New issues opened by external users.
2. Issues closed.
3. External pull requests.
4. Control-pack validation failures caught by tests.
5. Documentation page additions or improvements.
6. Benchmark runtime and row count coverage.
7. Rule-pack count and quality.
8. Odoo/SAP mapping improvements merged.
9. Downloads or installs if package distribution is added.
10. Number of real anonymized scenarios contributed.
11. Time to first successful sample workflow for a new user.
12. Security workflow pass/fail status.

## 23. What Must Not Be Done

1. Do not fake users, stars, downloads, logos, or testimonials.
2. Do not claim market leadership before evidence exists.
3. Do not add cloud upload to core workflows.
4. Do not build toy AI features.
5. Do not make direct ERP connector claims until implemented and tested.
6. Do not weaken deterministic controls.
7. Do not let commercial features remove value from the open-source core.
8. Do not accept live customer data in public issues.
9. Do not broaden beyond ERP audit intelligence before the beachhead works.
10. Do not ship user-facing features without documentation and tests.
