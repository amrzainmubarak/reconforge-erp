# Adoption Engine

The adoption system must create real usage and feedback. It must not fake momentum.

## 1. GitHub Optimization

- Keep README focused on the first successful workflow.
- Put Odoo/SAP export-based mapping profiles near the top.
- Show local-first and no-cloud-upload clearly.
- Link to rule-pack schema, export guides, control packs, examples, and screenshots.
- Keep maturity note visible.
- Add release notes for each meaningful version.

## 2. Issue Labels

Recommended labels:

- `area:mapping`
- `area:rules`
- `area:docs`
- `area:tests`
- `area:security`
- `area:studio`
- `erp:odoo`
- `erp:sap`
- `erp:erpnext`
- `erp:netsuite`
- `erp:dynamics`
- `good first issue`
- `help wanted`
- `needs-anonymized-sample`
- `commercial-boundary`

## 3. Good First Issues

Good first issues should be small and verifiable:

- Add an expected exception example to an existing pack.
- Add a missing field note to an export guide.
- Add a rule-pack invalid example.
- Improve a sample command.
- Add docs links between README and control pack docs.
- Add tests for a documentation file that must exist.

## 4. Help Wanted Issues

Help wanted issues can require domain experience:

- Validate Odoo stock valuation mapping fields.
- Validate SAP MB51/FAGLL03 layout variants.
- Add ERPNext CSV mapping profile.
- Add NetSuite saved-search mapping profile.
- Add Dynamics export mapping profile.
- Contribute anonymized field headers from a real export.

## 5. Discussions Strategy

Use GitHub Discussions for:

- Export mapping questions.
- Control-pack proposals.
- Anonymized scenario reviews.
- Release planning.
- Consultant implementation notes.
- Security/data privacy questions.

Do not use Discussions for private customer data.

## 6. Odoo Community Strategy

- Post export-based workflows in Odoo communities without claiming an Odoo module.
- Ask for field header feedback from Odoo implementers.
- Build compatibility notes by Odoo version and module.
- Engage OCA contributors respectfully; ReconForge is adjacent to Odoo modules, not a replacement for OCA.

## 7. SAP Consultant Strategy

- Focus on MB51, FAGLL03, and FBL3N export review.
- Ask consultants for anonymized layout variants and field naming.
- Avoid claims about SAP-certified integration.
- Publish practical examples for posting date, material document, reference, assignment, amount, cost center, and movement type.

## 8. Accounting / Audit LinkedIn Strategy

- Share practical lessons, not hype.
- Use screenshots from local sample outputs.
- Explain local-first evidence workflows.
- Ask for feedback from controllers and auditors.
- Avoid adoption claims unless backed by public evidence.

## 9. Python Open-Source Strategy

- Emphasize deterministic CLI, tests, YAML validation, and local reports.
- Make contribution tasks easy to run locally.
- Add type-safe, well-scoped issues.
- Avoid over-marketing to developers who do not care about ERP workflows.

## 10. Demo Video Plan

Create two videos:

- 90 seconds: install, doctor, validate sample data, run stock-GL, run Odoo/SAP pack, open report.
- 5 minutes: export mapping concept, rules, evidence binder, anonymization, and where the project is early.

## 11. Blog Post Topics

1. Why local-first ERP audit matters.
2. Why Excel reconciliation fails under audit pressure.
3. How to reconcile Odoo stock valuation exports to accounting lines.
4. How to inspect SAP MB51 and FAGLL03 exports locally.
5. Designing deterministic rule packs for audit evidence.
6. How anonymized ERP exports can improve open-source control packs.
7. Stock-to-GL matching explained for auditors and controllers.

## 12. Release Cadence

- Patch releases as needed for defects.
- Minor releases every 4 to 8 weeks while pre-1.0.
- Each release needs tests, docs, changelog, and migration notes if schemas change.
- Do not release empty roadmap-only versions.

## 13. Contributor Onboarding

- One-page contributor path.
- Rule-pack schema reference.
- Pack validation command.
- Sample data workflow.
- Pull request checklist.
- Security and data anonymization warnings.

## 14. First 100 Stars Plan

- Launch with honest positioning.
- Ask ERP, audit, accounting, and Python communities for feedback.
- Share one concrete demo workflow.
- Publish Odoo/SAP export guides.
- Convert feedback into issues and visible fixes.
- Do not run giveaways, fake engagement, or paid star campaigns.

## 15. First 10 Real Users Plan

- Recruit users who have a real export problem.
- Offer a 30-minute onboarding call or async walkthrough.
- Ask them to run sample data first, then anonymized headers.
- Track where they get stuck.
- Convert repeated friction into docs or code changes.

## 16. First 3 External Contributors Plan

- Prepare issues with clear files and acceptance criteria.
- Review quickly and kindly.
- Start with docs/mapping/rules contributions.
- Add contributors only after real merged work.
- Invite maintainers slowly and based on judgment.

## 17. First Pilot Implementation Plan

- Define pilot scope: one ERP, one period, stock-to-GL plus selected controls.
- Use anonymized samples for support.
- Document source exports, mapping, rules, exceptions, and evidence pack.
- Measure time to first output and time to reviewed exceptions.
- End with a written pilot report and a list of product gaps.

## 18. Feedback Loop

1. User runs sample workflow.
2. User maps their exports locally.
3. User shares anonymized headers or synthetic scenario.
4. Maintainers turn friction into issues.
5. Fixes land with docs and tests.
6. Release notes explain what improved.

## 19. Trust-Building Loop

1. Make claims only from working features.
2. Show commands and outputs.
3. Keep security posture visible.
4. Publish benchmarks and limitations.
5. Respond to issues without defensiveness.
6. Maintain a clear commercial boundary.

## 20. What Not To Do

- Do not fake stars, users, logos, downloads, or testimonials.
- Do not scrape or upload customer data.
- Do not pitch as a replacement for SAP, Odoo, BlackLine, or audit judgment.
- Do not add broad AI claims.
- Do not chase generic accounting features before the ERP audit wedge works.
