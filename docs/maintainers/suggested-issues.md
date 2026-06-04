# Suggested Issue Backlog

These are ready-to-copy GitHub issue drafts. Do not create the issues automatically unless a maintainer explicitly decides to publish them.

## 1. Good First Issue: Add CLI Command Examples To Mapping Profile READMEs

**Problem:** Some control-pack READMEs are easier to use when they include a direct `reconforge mappings validate` command.

**Proposed solution:** Review ERP export profile READMEs and add a short validation command where missing.

**Acceptance criteria:**

- Each changed README uses an existing command.
- No direct connector claims are added.
- Markdown links and paths are valid.

**Labels:** `good first issue`, `documentation`, `erp-profile`

**Difficulty:** Beginner

## 2. Good First Issue: Add Privacy Reminder To Rule Pack READMEs

**Problem:** Contributors may not notice that sample headers and scenarios must be synthetic or anonymized.

**Proposed solution:** Add a short privacy note to rule-pack READMEs that lack one.

**Acceptance criteria:**

- The note warns against live ERP data.
- The wording is concise and consistent.
- No generated outputs are committed.

**Labels:** `good first issue`, `documentation`, `rule-pack`

**Difficulty:** Beginner

## 3. Documentation: Improve Client Pack Sharing Checklist

**Problem:** Users need clearer steps for deciding which generated client pack files can be shared externally.

**Proposed solution:** Update client handoff and demo output docs with a short review checklist.

**Acceptance criteria:**

- Checklist distinguishes summary-only, redacted, and raw-record outputs.
- Docs do not imply compliance certification.
- Commands remain current.

**Labels:** `documentation`, `audit-workflow`, `commercial-docs`

**Difficulty:** Beginner

## 4. Documentation: Add Glossary For Finance And Audit Terms

**Problem:** New contributors may not know terms such as WIP, stock-to-GL, evidence binder, accepted risk, and source-document traceability.

**Proposed solution:** Add or extend a glossary page using plain-language definitions.

**Acceptance criteria:**

- Definitions are concise and non-legal.
- Terms link to relevant docs where useful.
- No audit opinion or compliance claims are added.

**Labels:** `documentation`, `good first issue`

**Difficulty:** Beginner

## 5. ERP Profile Improvements: Add Sanitized Header Examples For ERPNext

**Problem:** The ERPNext export profile would be easier to evaluate with sanitized header examples.

**Proposed solution:** Add synthetic header-only examples or documentation showing expected fields.

**Acceptance criteria:**

- Examples include headers only or synthetic rows.
- Mapping validation still passes.
- Docs state the profile is export-based.

**Labels:** `erp-profile`, `documentation`, `testing`

**Difficulty:** Intermediate

## 6. ERP Profile Improvements: Review NetSuite Saved Search Field Names

**Problem:** NetSuite saved search names can vary by implementation, making mapping docs harder to follow.

**Proposed solution:** Review the NetSuite profile docs and add alternate sanitized field-name notes where appropriate.

**Acceptance criteria:**

- Alternate names are framed as examples, not vendor guarantees.
- Mapping validation passes.
- No direct connector or official certification claims are added.

**Labels:** `erp-profile`, `documentation`

**Difficulty:** Intermediate

## 7. Testing: Add Regression Test For Redacted Client Pack Text Files

**Problem:** Redacted client packs should not leak names or amounts in copied text-based outputs.

**Proposed solution:** Add a focused test around redacted client-pack generation.

**Acceptance criteria:**

- Test covers `--redact-names`, `--redact-amounts`, and `--exclude-raw-records`.
- Test uses synthetic data only.
- Existing tests still pass.

**Labels:** `testing`, `security`, `audit-workflow`

**Difficulty:** Intermediate

## 8. Testing: Add Mapping Validation Fixture For Dynamics Profile

**Problem:** Dynamics export profile changes should be protected by a small validation fixture.

**Proposed solution:** Add a synthetic fixture or test that validates the Dynamics mapping profile.

**Acceptance criteria:**

- Test invokes the mapping validator or CLI path.
- Fixture contains no private data.
- Existing profile validation commands still pass.

**Labels:** `testing`, `erp-profile`

**Difficulty:** Intermediate

## 9. Security Hardening: Review Generated HTML Link Encoding

**Problem:** Generated reports must keep href values safely encoded when file names or paths contain spaces or special characters.

**Proposed solution:** Audit report and evidence HTML generation, then add regression tests for URL-quoted href path segments.

**Acceptance criteria:**

- Tests cover special characters in safe generated paths.
- HTML text is escaped separately from href encoding.
- No direct file-serving behavior is introduced.

**Labels:** `security`, `testing`, `audit-workflow`

**Difficulty:** Intermediate

## 10. Security Hardening: Add Raw Exception Leakage Regression Test

**Problem:** User-facing outputs should not render raw internal exceptions.

**Proposed solution:** Add or extend tests that simulate malformed input and assert safe user-facing error text.

**Acceptance criteria:**

- Test covers at least one CLI or Studio-facing path.
- Raw exception internals are not rendered.
- Developer diagnostics remain available in controlled logs if appropriate.

**Labels:** `security`, `testing`

**Difficulty:** Intermediate

## 11. Deployment: Validate Docker Documentation Against CI Workflow

**Problem:** Docker docs should match the current CI build and container doctor workflow.

**Proposed solution:** Review Docker docs and update wording to separate CI build support from local runtime verification.

**Acceptance criteria:**

- No local runtime verification claim is added unless commands pass.
- Docs link to the Docker verification report.
- Docker commands remain copyable.

**Labels:** `deployment`, `docker`, `documentation`

**Difficulty:** Beginner

## 12. Deployment: Add Troubleshooting Notes For Stale Console Scripts

**Problem:** Editable installs can leave users running stale `reconforge` console scripts.

**Proposed solution:** Add troubleshooting guidance to getting-started or release docs.

**Acceptance criteria:**

- Includes `python -m reconforge.cli doctor`.
- Includes reinstall guidance.
- Does not recommend destructive environment changes.

**Labels:** `deployment`, `documentation`, `good first issue`

**Difficulty:** Beginner

## 13. Audit Workflow: Improve Evidence Binder Field Explanations

**Problem:** Evidence binder files are useful, but contributors may not understand which fields support review.

**Proposed solution:** Add concise field explanations for evidence summary, source records, match candidates, triggered rules, and audit trail files.

**Acceptance criteria:**

- Explanations are factual and not legal advice.
- Docs state evidence manifests are integrity aids, not signatures.
- No audit opinion claim is added.

**Labels:** `audit-workflow`, `documentation`

**Difficulty:** Beginner

## 14. Audit Workflow: Add Accepted-Risk Review Scenario To Docs

**Problem:** Review workflow docs should clarify how accepted-risk status should be documented.

**Proposed solution:** Add a synthetic example showing reviewer note, decision reason, and accepted-risk reason.

**Acceptance criteria:**

- Scenario uses synthetic exception IDs and names.
- Wording avoids audit sign-off claims.
- Relevant CLI or Studio commands remain accurate.

**Labels:** `audit-workflow`, `documentation`, `pilot-feedback`

**Difficulty:** Beginner

## 15. Accessibility: Review Static Report Heading Order

**Problem:** Static HTML reports should be easier to navigate with assistive technologies.

**Proposed solution:** Review generated report heading order and landmark structure.

**Acceptance criteria:**

- Heading hierarchy is logical.
- Changes do not break existing report tests.
- Visual layout remains readable.

**Labels:** `accessibility`, `testing`, `documentation`

**Difficulty:** Intermediate

## 16. Accessibility: Improve Color Contrast Notes For Report Themes

**Problem:** Report themes should avoid low-contrast combinations in important exception and risk indicators.

**Proposed solution:** Review report CSS and document or adjust contrast where needed.

**Acceptance criteria:**

- Any CSS changes are tested or manually smoke-checked.
- Risk labels remain readable.
- No large redesign is introduced.

**Labels:** `accessibility`, `audit-workflow`

**Difficulty:** Intermediate

## 17. Demo Assets: Add Screenshot Refresh Checklist

**Problem:** Screenshot assets need a repeatable refresh process from synthetic outputs.

**Proposed solution:** Add a checklist that documents demo generation, screenshot capture, privacy review, and docs update steps.

**Acceptance criteria:**

- Checklist uses synthetic data only.
- No generated screenshots are required for this issue.
- Docs avoid adoption or customer claims.

**Labels:** `documentation`, `commercial-docs`, `testing`

**Difficulty:** Beginner

## 18. Demo Assets: Add Demo Script For Export Profile Validation

**Problem:** The 10-minute demo focuses on reports, but mapping validation also needs a clear walkthrough.

**Proposed solution:** Add a short script or doc section showing how to validate included ERP export profiles.

**Acceptance criteria:**

- Includes Odoo, SAP, ERPNext, Dynamics, and NetSuite validation commands.
- States profiles are export-based.
- Does not claim direct ERP connectivity.

**Labels:** `documentation`, `erp-profile`, `good first issue`

**Difficulty:** Beginner

## 19. Sample Data: Add Synthetic Edge Case For Unmatched GL Row

**Problem:** Contributors need clear sample data for unmatched GL behavior.

**Proposed solution:** Add a small synthetic fixture or test case that demonstrates unmatched GL classification.

**Acceptance criteria:**

- Data is synthetic.
- Expected exception behavior is asserted.
- Existing reconciliation tests pass.

**Labels:** `sample-data`, `testing`, `audit-workflow`

**Difficulty:** Intermediate

## 20. Sample Data: Document Anonymized Scenario Submission Format

**Problem:** Practitioners may want to submit scenarios without exposing private ERP data.

**Proposed solution:** Add a short guide for submitting anonymized scenarios with sanitized headers, small row samples, expected exceptions, and privacy checks.

**Acceptance criteria:**

- Guide warns against live data and hidden workbook sheets.
- Includes a safe issue/discussion submission format.
- Links to anonymization and security docs.

**Labels:** `sample-data`, `documentation`, `pilot-feedback`

**Difficulty:** Beginner

## 21. Close Workflow: Add Period Close Readiness Score

**Problem:** The local close checklist shows status counts, but controllers need a concise readiness score that combines blocked tasks, incomplete tasks, unresolved high-risk exceptions, and evidence coverage.

**Proposed solution:** Add a deterministic readiness summary from local close, review, evidence, and management-pack outputs.

**Acceptance criteria:**

- Uses local files only.
- Does not imply audit sign-off or legal certification.
- Includes tests for missing optional inputs and malformed close state.

**Labels:** `close-workflow`, `reporting`, `testing`

**Difficulty:** Intermediate

## 22. Controls: Add Local Control Testing Register

**Problem:** The control matrix exports control rows, but there is no local test execution register.

**Proposed solution:** Add a file-based control testing register with control ID, test status, tester, evidence reference, exception note, and updated timestamp.

**Acceptance criteria:**

- Uses local JSON/CSV outputs only.
- Escapes rendered values.
- Avoids compliance certification or audit opinion wording.

**Labels:** `controls`, `grc-lite`, `audit-workflow`

**Difficulty:** Intermediate

## 23. ERP Profiles: Add Profile Confidence Scoring

**Problem:** Mapping profiles can validate structurally, but users need a simple confidence signal for header coverage and missing fields.

**Proposed solution:** Extend mapping inspection with profile confidence scoring from local export headers.

**Acceptance criteria:**

- Scores are explainable and deterministic.
- Missing columns are listed plainly.
- No direct connector or vendor certification claims are added.

**Labels:** `erp-profile`, `data-quality`, `testing`

**Difficulty:** Intermediate

## 24. Studio: Add Editable Close Workflow After Security Review

**Problem:** Studio now has a read-only close checklist page. Editing close tasks in Studio would be useful but increases local write surface.

**Proposed solution:** Design and implement close task update actions after reviewing CSRF, validation, escaping, and local state behavior.

**Acceptance criteria:**

- Status validation matches CLI behavior.
- User-controlled values are escaped.
- Tests cover invalid status and malformed input.
- Docs state there is no auth/RBAC.

**Labels:** `studio`, `close-workflow`, `security`

**Difficulty:** Intermediate
